#!/usr/bin/env python3
"""
Modern Recipe Management System (RMS)
=====================================
A consolidated, feature-rich recipe management system with cost calculation,
unit conversion, and professional recipe scaling capabilities.

Author: Claude Code & User
Version: 2.0
"""

import sqlite3
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
import argparse
from tabulate import tabulate


@dataclass
class Ingredient:
    """Data class for ingredient information."""
    id: int
    name: str
    category: str
    # Purchase level
    purchase_unit: str  # How you buy it (case, bag, etc.)
    purchase_price: float  # Price per purchase unit
    # Inventory level
    inventory_unit: str  # What you track in stock (#10 can, lb, ea, etc.)
    units_per_purchase: float  # How many inventory units per purchase unit
    cost_per_inventory_unit: float  # Cost per inventory unit
    on_hand: float  # Inventory on hand (in inventory units)
    # Recipe level
    recipe_unit: str  # What recipes use (C, oz, ea, etc.)
    recipe_units_per_inventory: float  # How many recipe units per inventory unit
    cost_per_recipe_unit: float  # Cost per recipe unit (with yield applied)
    yield_percent: float  # Yield percentage
    # Metadata (all have defaults)
    par_level: float = 0.0  # Par level (in inventory units)
    supplier: str = ""
    notes: str = ""
    allergens: str = ""


@dataclass
class Recipe:
    """Data class for recipe information."""
    name: str
    servings: int
    q_factor: float = 0.04
    description: str = ""
    prep_time: int = 0  # minutes
    cook_time: int = 0  # minutes
    instructions: str = ""
    whole_unit: bool = False  # True for recipes that come in discrete units (pies, cakes, etc.)


@dataclass
class RecipeIngredient:
    """Data class for recipe-ingredient associations."""
    recipe_name: str
    ingredient_name: str
    quantity: float
    unit: str


@dataclass
class Plate:
    """Data class for plate/menu item information."""
    name: str
    category: str
    description: str = ""


@dataclass
class PlateIngredient:
    """Data class for plate-ingredient associations."""
    plate_name: str
    ingredient_name: str
    quantity: float
    unit: str


class UnitConverter:
    """Handles all unit conversions for the RMS."""

    def __init__(self):
        self.conversion_factors = {
            # Volume conversions (using JSON notation: Gal., qt., pt., oz.)
            ("Gal.", "qt."): 4, ("Gal.", "pt."): 8, ("Gal.", "C"): 16,
            ("Gal.", "oz."): 128, ("Gal.", "T"): 256, ("Gal.", "t"): 768,
            ("Gal.", "L"): 3.78541, ("Gal.", "mL"): 3785.41,
            ("Gal.", "lb"): 8,  # Weight-to-volume for water/liquids

            ("qt.", "Gal."): 0.25, ("qt.", "pt."): 2, ("qt.", "C"): 4,
            ("qt.", "oz."): 32, ("qt.", "T"): 64, ("qt.", "t"): 192,
            ("qt.", "L"): 0.946353, ("qt.", "mL"): 946.353,
            ("qt.", "lb"): 2,  # Weight-to-volume for water/liquids

            ("pt.", "Gal."): 0.125, ("pt.", "qt."): 0.5, ("pt.", "C"): 2,
            ("pt.", "oz."): 16, ("pt.", "T"): 32, ("pt.", "t"): 96,
            ("pt.", "L"): 0.473176, ("pt.", "mL"): 473.176,
            ("pt.", "lb"): 1,  # Weight-to-volume for water/liquids

            ("C", "Gal."): 0.0625, ("C", "qt."): 0.25, ("C", "pt."): 0.5,
            ("C", "oz."): 8, ("C", "T"): 16, ("C", "t"): 48,
            ("C", "L"): 0.236588, ("C", "mL"): 236.588,
            ("C", "lb"): 0.5,  # Weight-to-volume for water/liquids

            ("oz.", "Gal."): 0.0078125, ("oz.", "qt."): 0.03125, ("oz.", "pt."): 0.0625,
            ("oz.", "C"): 0.125, ("oz.", "T"): 2, ("oz.", "t"): 6,
            ("oz.", "L"): 0.0295735, ("oz.", "mL"): 29.5735,
            ("oz.", "lb"): 0.0625,

            ("T", "Gal."): 0.00390625, ("T", "qt."): 0.015625, ("T", "pt."): 0.03125,
            ("T", "C"): 0.0625, ("T", "oz."): 0.5, ("T", "t"): 3,
            ("T", "L"): 0.0147868, ("T", "mL"): 14.7868,
            ("T", "lb"): 0.03125,  # Approximate for dense ingredients
            ("T", "bunch"): 0.0625,  # Tablespoon to bunch for herbs

            ("t", "Gal."): 0.00130208, ("t", "qt."): 0.00520833, ("t", "pt."): 0.0104167,
            ("t", "C"): 0.0208333, ("t", "oz."): 0.166667, ("t", "T"): 0.333333,
            ("t", "L"): 0.00492892, ("t", "mL"): 4.92892,
            ("t", "lb"): 0.0104167,  # Approximate for dense ingredients like salt

            # Weight conversions
            ("lb", "oz."): 16, ("lb", "g"): 453.592, ("lb", "Kg"): 0.453592,
            ("lb", "Gal."): 0.125, ("lb", "qt."): 0.5, ("lb", "pt."): 1, ("lb", "C"): 2,  # Weight-to-volume
            ("lb", "T"): 32, ("lb", "t"): 96,  # Weight-to-volume for dense ingredients
            ("lb", "L"): 0.453592, ("lb", "mL"): 453.592,

            ("oz.", "lb"): 0.0625, ("oz.", "g"): 28.3495,
            ("g", "lb"): 0.00220462, ("g", "oz."): 0.035274,
            ("Kg", "lb"): 2.20462,

            ("L", "Gal."): 0.264172, ("L", "qt."): 1.05669, ("L", "pt."): 2.11338,
            ("L", "C"): 4.22675, ("L", "oz."): 33.814, ("L", "T"): 67.628, ("L", "t"): 202.884,
            ("L", "lb"): 2.20462, ("L", "mL"): 1000,

            ("mL", "Gal."): 0.000264172, ("mL", "qt."): 0.00105669, ("mL", "pt."): 0.00211338,
            ("mL", "C"): 0.00422675, ("mL", "oz."): 0.033814, ("mL", "T"): 0.067628, ("mL", "t"): 0.202884,
            ("mL", "lb"): 0.00220462, ("mL", "L"): 0.001,

            # Count conversions
            ("doz.", "ea"): 12, ("ea", "doz."): 0.0833333,
            ("case", "ea"): 24, ("ea", "case"): 0.0416667,

            # Special conversions
            ("clove", "lb"): 0.02, ("lb", "clove"): 50,
            ("tbsp", "clove"): 3,  # 1 clove ≈ 3 tbsp when minced/chopped
            ("bunch", "t"): 70, ("t", "bunch"): 0.0142857,
            ("bunch", "T"): 16,  # 1 bunch ≈ 16 tbsp for herbs
            ("loaf", "slice"): 15, ("slice", "loaf"): 0.0666667,

            # Can conversions (standard #10 can)
            ("can", "oz."): 106, ("oz.", "can"): 0.00943396,  # #10 can = 106 oz
            ("can", "C"): 13.25, ("C", "can"): 0.0754717,  # #10 can = 13.25 cups (106 oz / 8 oz per cup)

            # Produce conversions
            ("head", "ea"): 1.0, ("ea", "head"): 1.0,  # Head = each for lettuce/cabbage

            # Produce weight conversions (approximate averages)
            ("ea-cucumber", "oz"): 3.5, ("oz", "ea-cucumber"): 0.2857,  # Persian cucumber ~3.5 oz
            ("ea-plum-tomato", "oz"): 2.5, ("oz", "ea-plum-tomato"): 0.4,  # Plum tomato ~2.5 oz
            ("ea-tomato", "oz"): 5.0, ("oz", "ea-tomato"): 0.2,  # Regular tomato ~5 oz
            ("ea-olive", "oz"): 0.15, ("oz", "ea-olive"): 6.67,  # Cocktail olive ~0.15 oz (about 100 per lb)
            ("ea-lemon", "oz"): 3.5, ("oz", "ea-lemon"): 0.2857,  # Average lemon ~3.5 oz
            ("ea-shrimp-16-20", "lb"): 0.0556, ("lb", "ea-shrimp-16-20"): 18,  # 16/20 count = ~18 shrimp per lb

            # Count unit equivalencies
            ("pieces", "each"): 1.0, ("each", "pieces"): 1.0,
            ("piece", "each"): 1.0, ("each", "piece"): 1.0,
            ("pieces", "ea"): 1.0, ("ea", "pieces"): 1.0,
            ("piece", "ea"): 1.0, ("ea", "piece"): 1.0,

            # Culinary unit conversions (approximate small quantities)
            ("pinch", "t"): 0.0625, ("t", "pinch"): 16,  # 1/16 tsp
            ("sprinkle", "t"): 0.125, ("t", "sprinkle"): 8,  # 1/8 tsp
            ("dash", "t"): 0.125, ("t", "dash"): 8,  # 1/8 tsp
            ("drizzle", "T"): 0.5, ("T", "drizzle"): 2,  # 1/2 tbsp = 1.5 tsp
            ("dollop", "T"): 1.0, ("T", "dollop"): 1,  # 1 tbsp
            ("garnish", "t"): 0.25, ("t", "garnish"): 4,  # 1/4 tsp
            ("sprig", "t"): 0.125, ("t", "sprig"): 8,  # 1/8 tsp
            ("dust", "t"): 0.0625, ("t", "dust"): 16,  # 1/16 tsp
            ("smear", "t"): 0.5, ("t", "smear"): 2,  # 1/2 tsp
            ("quenelle", "T"): 1.0, ("T", "quenelle"): 1,  # 1 tbsp

            # Fractional produce units
            ("wedge", "ea"): 0.25, ("ea", "wedge"): 4,  # 1 wedge = 1/4 of a whole
            ("half", "ea"): 0.5, ("ea", "half"): 2,  # 1 half = 1/2 of a whole
            ("quarter", "ea"): 0.25, ("ea", "quarter"): 4,  # 1 quarter = 1/4 of a whole
            ("slice", "ea"): 0.0625, ("ea", "slice"): 16,  # Approximate: 16 slices per whole
        }

    def convert(self, quantity: float, from_unit: str, to_unit: str) -> float:
        """Convert quantity from one unit to another."""
        # Normalize unit names (map to JSON-style notation)
        unit_aliases = {
            # Tablespoon/Teaspoon aliases
            "T": "T", "tbsp": "T", "tablespoon": "T", "tablespoons": "T",
            "tsp": "t", "teaspoon": "t", "teaspoons": "t",

            # Volume aliases (to JSON notation with periods)
            "c": "C", "cup": "C", "cups": "C",
            "ounce": "oz.", "ounces": "oz.", "oz": "oz.",
            "gal": "Gal.", "gallon": "Gal.", "gallons": "Gal.",
            "qt": "qt.", "quart": "qt.", "quarts": "qt.",
            "pt": "pt.", "pint": "pt.", "pints": "pt.",

            # Weight aliases
            "pound": "lb", "pounds": "lb",

            # Count aliases
            "each": "ea", "eaches": "ea",
            "doz": "doz.", "dozen": "doz.",
        }
        from_unit = unit_aliases.get(from_unit, from_unit)
        to_unit = unit_aliases.get(to_unit, to_unit)

        if from_unit == to_unit:
            return quantity

        key = (from_unit, to_unit)
        if key in self.conversion_factors:
            return quantity * self.conversion_factors[key]

        # Try reverse conversion
        reverse_key = (to_unit, from_unit)
        if reverse_key in self.conversion_factors:
            return quantity / self.conversion_factors[reverse_key]

        # Try chained conversions through common intermediates
        intermediates = ["t", "T", "C", "oz.", "oz", "lb", "Gal.", "gal", "ea"]
        for intermediate in intermediates:
            try:
                if (from_unit, intermediate) in self.conversion_factors or (intermediate, from_unit) in self.conversion_factors:
                    if (intermediate, to_unit) in self.conversion_factors or (to_unit, intermediate) in self.conversion_factors:
                        # Convert from_unit -> intermediate -> to_unit
                        temp = self.convert(quantity, from_unit, intermediate)
                        return self.convert(temp, intermediate, to_unit)
            except ValueError:
                continue

        raise ValueError(f"No conversion available from {from_unit} to {to_unit}")


class DatabaseManager:
    """Manages all database operations for the RMS."""

    def __init__(self, db_path: str = "rms_unified.db"):
        self.db_path = db_path
        self.converter = UnitConverter()
        self._init_database()

    def _init_database(self):
        """Initialize the database with proper schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create ingredients table with bulk purchasing focus
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ingredients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    category TEXT NOT NULL,
                    bulk_unit TEXT NOT NULL,
                    bulk_quantity REAL NOT NULL,
                    bulk_price REAL NOT NULL,
                    recipe_unit TEXT NOT NULL,
                    unit_price REAL NOT NULL,
                    on_hand REAL NOT NULL,
                    supplier TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    yield_percent REAL DEFAULT 95.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create recipes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recipes (
                    name TEXT PRIMARY KEY,
                    servings INTEGER NOT NULL,
                    q_factor REAL DEFAULT 0.04,
                    description TEXT DEFAULT '',
                    prep_time INTEGER DEFAULT 0,
                    cook_time INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create recipe_ingredients junction table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recipe_ingredients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipe_name TEXT NOT NULL,
                    ingredient_name TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    unit TEXT NOT NULL,
                    FOREIGN KEY (recipe_name) REFERENCES recipes(name) ON DELETE CASCADE,
                    FOREIGN KEY (ingredient_name) REFERENCES ingredients(name) ON DELETE CASCADE,
                    UNIQUE(recipe_name, ingredient_name)
                )
            """)

            # Create recipe_steps table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recipe_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipe_name TEXT NOT NULL,
                    step_number INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    FOREIGN KEY (recipe_name) REFERENCES recipes(name) ON DELETE CASCADE,
                    UNIQUE(recipe_name, step_number)
                )
            """)

            conn.commit()
            self._migrate_ingredient_schema()

    def _migrate_ingredient_schema(self):
        """Migrate existing ingredient data to new bulk purchasing schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Check if migration is needed
            cursor.execute("PRAGMA table_info(ingredients)")
            columns = [col[1] for col in cursor.fetchall()]

            # Check if already using new schema (purchase_unit exists)
            if 'purchase_unit' in columns:
                # Already migrated to new schema, skip migration
                return

            if 'bulk_unit' not in columns:
                print("Migrating ingredient database to bulk purchasing schema...")

                # Create new table with bulk purchasing structure
                cursor.execute("""
                    CREATE TABLE ingredients_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        category TEXT NOT NULL,
                        bulk_unit TEXT NOT NULL,
                        bulk_quantity REAL NOT NULL,
                        bulk_price REAL NOT NULL,
                        recipe_unit TEXT NOT NULL,
                        unit_price REAL NOT NULL,
                        on_hand REAL NOT NULL,
                        supplier TEXT DEFAULT '',
                        notes TEXT DEFAULT '',
                        yield_percent REAL DEFAULT 95.0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Migrate existing data with bulk purchasing defaults
                cursor.execute("""
                    INSERT INTO ingredients_new
                    (name, category, bulk_unit, bulk_quantity, bulk_price, recipe_unit,
                     unit_price, on_hand, supplier, notes, yield_percent)
                    SELECT
                        name,
                        CASE
                            WHEN category IN ('Dairy and Eggs', 'Dairy') THEN 'Dairy and Eggs'
                            WHEN category IN ('Spices and Seasonings', 'Spices And Seasonings') THEN 'Spices and Seasonings'
                            WHEN category IN ('Oils and Vinegars', 'Oils Vinegars Water') THEN 'Oils and Vinegars'
                            WHEN category = 'Nuts And Seeds' THEN 'Nuts and Seeds'
                            ELSE category
                        END as category,
                        CASE
                            WHEN purchase_unit LIKE '%case%' THEN 'case'
                            WHEN purchase_unit LIKE '%sack%' THEN 'sack'
                            WHEN purchase_unit LIKE '%box%' THEN 'box'
                            WHEN purchase_unit LIKE '%bag%' THEN 'bag'
                            WHEN purchase_unit LIKE '%lb%' THEN '50 lb case'
                            WHEN purchase_unit LIKE '%gal%' THEN '4 gal case'
                            ELSE 'case'
                        END as bulk_unit,
                        CASE
                            WHEN purchase_unit LIKE '%case%' THEN 24.0
                            WHEN purchase_unit LIKE '%sack%' THEN 50.0
                            WHEN purchase_unit LIKE '%box%' THEN 12.0
                            WHEN purchase_unit LIKE '%bag%' THEN 25.0
                            WHEN purchase_unit LIKE '%lb%' THEN 50.0
                            WHEN purchase_unit LIKE '%gal%' THEN 4.0
                            ELSE 24.0
                        END as bulk_quantity,
                        unit_price * CASE
                            WHEN purchase_unit LIKE '%case%' THEN 24.0
                            WHEN purchase_unit LIKE '%sack%' THEN 50.0
                            WHEN purchase_unit LIKE '%box%' THEN 12.0
                            WHEN purchase_unit LIKE '%bag%' THEN 25.0
                            WHEN purchase_unit LIKE '%lb%' THEN 50.0
                            WHEN purchase_unit LIKE '%gal%' THEN 4.0
                            ELSE 24.0
                        END as bulk_price,
                        base_unit as recipe_unit,
                        unit_price,
                        on_hand,
                        '' as supplier,
                        '' as notes,
                        yield_percent
                    FROM ingredients
                """)

                # Drop old table and rename new one
                cursor.execute("DROP TABLE ingredients")
                cursor.execute("ALTER TABLE ingredients_new RENAME TO ingredients")

                conn.commit()
                print("Migration completed successfully!")

    def update_ingredient_price(self, ingredient_id: int, bulk_price: float) -> bool:
        """Update the bulk price for an ingredient and recalculate unit price."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get bulk quantity to calculate unit price
                cursor.execute("SELECT bulk_quantity FROM ingredients WHERE id = ?", (ingredient_id,))
                result = cursor.fetchone()
                if not result:
                    return False

                bulk_quantity = result[0]
                unit_price = bulk_price / bulk_quantity if bulk_quantity > 0 else 0

                cursor.execute("""
                    UPDATE ingredients
                    SET bulk_price = ?, unit_price = ?
                    WHERE id = ?
                """, (bulk_price, unit_price, ingredient_id))

                conn.commit()
                return True
        except Exception:
            return False

    def get_ingredients_by_category(self) -> Dict[str, List[Ingredient]]:
        """Get ingredients organized by category with alphabetical sorting."""
        ingredients = self.get_ingredients()
        categories = {}

        for ingredient in ingredients:
            if ingredient.category not in categories:
                categories[ingredient.category] = []
            categories[ingredient.category].append(ingredient)

        # Sort categories and ingredients within each category
        sorted_categories = {}
        for category in sorted(categories.keys()):
            sorted_categories[category] = sorted(categories[category], key=lambda x: x.name)

        return sorted_categories

    def add_ingredient(self, ingredient: Ingredient) -> bool:
        """Add a new ingredient to the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO ingredients
                    (name, category, bulk_unit, bulk_quantity, bulk_price, recipe_unit,
                     unit_price, on_hand, supplier, notes, yield_percent)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (ingredient.name, ingredient.category, ingredient.bulk_unit,
                      ingredient.bulk_quantity, ingredient.bulk_price, ingredient.recipe_unit,
                      ingredient.unit_price, ingredient.on_hand, ingredient.supplier,
                      ingredient.notes, ingredient.yield_percent))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def get_ingredients(self, category: str = None) -> List[Ingredient]:
        """Get all ingredients, optionally filtered by category."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute("""SELECT id, name, category,
                                 purchase_unit, purchase_price,
                                 inventory_unit, units_per_purchase, cost_per_inventory_unit, on_hand,
                                 recipe_unit, recipe_units_per_inventory, cost_per_recipe_unit, yield_percent,
                                 par_level, supplier, notes, allergens
                                 FROM ingredients WHERE category = ? ORDER BY name""", (category,))
            else:
                cursor.execute("""SELECT id, name, category,
                                 purchase_unit, purchase_price,
                                 inventory_unit, units_per_purchase, cost_per_inventory_unit, on_hand,
                                 recipe_unit, recipe_units_per_inventory, cost_per_recipe_unit, yield_percent,
                                 par_level, supplier, notes, allergens
                                 FROM ingredients ORDER BY category, name""")

            return [Ingredient(*row) for row in cursor.fetchall()]

    def add_recipe(self, recipe: Recipe) -> bool:
        """Add a new recipe to the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO recipes (name, servings, q_factor, description, prep_time, cook_time, instructions, whole_unit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (recipe.name, recipe.servings, recipe.q_factor, recipe.description,
                      recipe.prep_time, recipe.cook_time, recipe.instructions, recipe.whole_unit))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def get_recipes(self) -> List[Recipe]:
        """Get all recipes."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, servings, q_factor, description, prep_time, cook_time, instructions, whole_unit FROM recipes ORDER BY name")
            return [Recipe(*row) for row in cursor.fetchall()]

    def update_recipe(self, original_name: str, recipe: Recipe) -> bool:
        """Update an existing recipe."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE recipes
                    SET name = ?, servings = ?, q_factor = ?, description = ?,
                        prep_time = ?, cook_time = ?, instructions = ?, whole_unit = ?
                    WHERE name = ?
                """, (recipe.name, recipe.servings, recipe.q_factor, recipe.description,
                      recipe.prep_time, recipe.cook_time, recipe.instructions, recipe.whole_unit, original_name))

                # If recipe name changed, update recipe_ingredients table
                if original_name != recipe.name:
                    cursor.execute("""
                        UPDATE recipe_ingredients
                        SET recipe_name = ?
                        WHERE recipe_name = ?
                    """, (recipe.name, original_name))

                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False

    def add_recipe_ingredient(self, recipe_ingredient: RecipeIngredient) -> bool:
        """Add an ingredient to a recipe."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO recipe_ingredients
                    (recipe_name, ingredient_name, quantity, unit)
                    VALUES (?, ?, ?, ?)
                """, (recipe_ingredient.recipe_name, recipe_ingredient.ingredient_name,
                      recipe_ingredient.quantity, recipe_ingredient.unit))
                conn.commit()
                return True
        except sqlite3.Error:
            return False

    def get_recipe_ingredients(self, recipe_name: str) -> List[RecipeIngredient]:
        """Get all ingredients for a specific recipe."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT recipe_name, ingredient_name, quantity, unit
                FROM recipe_ingredients
                WHERE recipe_name = ?
                ORDER BY ingredient_name
            """, (recipe_name,))
            return [RecipeIngredient(*row) for row in cursor.fetchall()]

    def calculate_recipe_cost(self, recipe_name: str) -> Dict[str, Any]:
        """Calculate the total cost and cost per serving for a recipe."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Get recipe info with prep_factor
            cursor.execute("SELECT servings, prep_factor FROM recipes WHERE name = ?", (recipe_name,))
            recipe_data = cursor.fetchone()
            if not recipe_data:
                raise ValueError(f"Recipe '{recipe_name}' not found")

            servings, prep_factor = recipe_data
            if prep_factor is None:
                prep_factor = 0.10

            # Get recipe ingredients with their costs
            cursor.execute("""
                SELECT ri.ingredient_name, ri.quantity, ri.unit,
                       i.cost_per_recipe_unit, i.recipe_unit
                FROM recipe_ingredients ri
                JOIN ingredients i ON ri.ingredient_name = i.name
                WHERE ri.recipe_name = ?
            """, (recipe_name,))

            ingredient_costs = []
            total_cost = 0.0

            for row in cursor.fetchall():
                ing_name, quantity, unit, cost_per_recipe_unit, recipe_unit = row

                try:
                    # Convert quantity to recipe unit for calculation
                    if unit != recipe_unit:
                        converted_quantity = self.converter.convert(quantity, unit, recipe_unit)
                    else:
                        converted_quantity = quantity

                    # Calculate cost (cost_per_recipe_unit already includes yield)
                    ingredient_cost = cost_per_recipe_unit * converted_quantity

                    # Round up sub-cent costs to $0.01 minimum
                    if ingredient_cost > 0 and ingredient_cost < 0.01:
                        rounded_cost = 0.01
                    else:
                        rounded_cost = round(ingredient_cost, 2)

                except ValueError as e:
                    # Conversion failed - use fallback cost to avoid giving ingredients away
                    print(f"Warning: {e}")
                    print(f"  Using fallback cost for {ing_name}: cost_per_recipe_unit * quantity = ${cost_per_recipe_unit} * {quantity}")

                    # Fallback: charge cost_per_recipe_unit * quantity directly, with $0.01 minimum
                    ingredient_cost = cost_per_recipe_unit * quantity
                    if ingredient_cost < 0.01:
                        rounded_cost = 0.01
                    else:
                        rounded_cost = round(ingredient_cost, 2)

                # Always include ingredient in cost, even if conversion failed
                total_cost += rounded_cost

                ingredient_costs.append({
                    'name': ing_name,
                    'quantity': quantity,
                    'unit': unit,
                    'cost': rounded_cost
                })

            # Apply prep_factor (labor, special equipment, planning) and calculate per serving
            prep_factor_cost = total_cost * prep_factor
            total_with_prep = total_cost + prep_factor_cost
            cost_per_serving = total_with_prep / servings

            return {
                'recipe_name': recipe_name,
                'servings': servings,
                'ingredient_cost': round(total_cost, 2),
                'prep_factor': prep_factor,
                'prep_factor_cost': round(prep_factor_cost, 2),
                'total_cost': round(total_with_prep, 2),
                'cost_per_serving': round(cost_per_serving, 2),
                'ingredient_breakdown': ingredient_costs
            }

    # Allergen Management Methods
    def get_recipe_allergens(self, recipe_name: str, visited: set = None) -> set:
        """Get all allergens present in a recipe (recursively checks sub-recipes)."""
        if visited is None:
            visited = set()

        # Prevent infinite recursion
        if recipe_name in visited:
            return set()

        visited.add(recipe_name)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            allergens = set()

            # Get all ingredients used in this recipe
            cursor.execute("""
                SELECT ingredient_name
                FROM recipe_ingredients
                WHERE recipe_name = ?
            """, (recipe_name,))

            ingredient_names = [row[0] for row in cursor.fetchall()]

            for ingredient_name in ingredient_names:
                # Check if this is a regular ingredient
                cursor.execute("""
                    SELECT allergens
                    FROM ingredients
                    WHERE name = ? AND allergens != ''
                """, (ingredient_name,))

                result = cursor.fetchone()
                if result and result[0]:
                    allergens.update(result[0].split(','))
                else:
                    # Check if this is a sub-recipe
                    cursor.execute("""
                        SELECT name
                        FROM recipes
                        WHERE name = ?
                    """, (ingredient_name,))

                    if cursor.fetchone():
                        # Recursively get allergens from the sub-recipe
                        sub_allergens = self.get_recipe_allergens(ingredient_name, visited)
                        allergens.update(sub_allergens)

            return allergens

    def get_plate_allergens(self, plate_name: str) -> set:
        """Get all allergens present in a plate (from recipes and direct ingredients)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            allergens = set()

            # Get allergens from recipes in the plate (using recursive method)
            cursor.execute("""
                SELECT recipe_name
                FROM plate_recipes
                WHERE plate_name = ?
            """, (plate_name,))

            for row in cursor.fetchall():
                recipe_name = row[0]
                recipe_allergens = self.get_recipe_allergens(recipe_name)
                allergens.update(recipe_allergens)

            # Get allergens from direct ingredients in the plate
            cursor.execute("""
                SELECT ingredient_name
                FROM plate_ingredients
                WHERE plate_name = ?
            """, (plate_name,))

            ingredient_names = [row[0] for row in cursor.fetchall()]

            for ingredient_name in ingredient_names:
                # Check if it's a regular ingredient
                cursor.execute("""
                    SELECT allergens
                    FROM ingredients
                    WHERE name = ? AND allergens != ''
                """, (ingredient_name,))

                result = cursor.fetchone()
                if result and result[0]:
                    allergens.update(result[0].split(','))

            return allergens

    def get_allergen_info(self, allergen_code: str) -> Dict[str, str]:
        """Get information about a specific allergen."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT code, name, icon, description
                FROM allergens
                WHERE code = ?
            """, (allergen_code,))

            row = cursor.fetchone()
            if row:
                return {
                    'code': row[0],
                    'name': row[1],
                    'icon': row[2],
                    'description': row[3]
                }
            return None

    # Plate Management Methods
    def get_plates(self) -> List[Plate]:
        """Get all plates."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, category, description FROM plates ORDER BY category, name")
            return [Plate(*row) for row in cursor.fetchall()]

    def add_plate(self, plate: Plate) -> bool:
        """Add a new plate to the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO plates (name, category, description)
                    VALUES (?, ?, ?)
                """, (plate.name, plate.category, plate.description))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def get_plate_ingredients(self, plate_name: str) -> List[PlateIngredient]:
        """Get all ingredients for a specific plate."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT plate_name, ingredient_name, quantity, unit
                FROM plate_ingredients
                WHERE plate_name = ?
                ORDER BY ingredient_name
            """, (plate_name,))
            return [PlateIngredient(*row) for row in cursor.fetchall()]

    def add_plate_ingredient(self, plate_ingredient: PlateIngredient) -> bool:
        """Add an ingredient to a plate."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO plate_ingredients
                    (plate_name, ingredient_name, quantity, unit)
                    VALUES (?, ?, ?, ?)
                """, (plate_ingredient.plate_name, plate_ingredient.ingredient_name,
                      plate_ingredient.quantity, plate_ingredient.unit))
                conn.commit()
                return True
        except sqlite3.Error:
            return False

    def calculate_plate_cost(self, plate_name: str) -> Dict[str, Any]:
        """Calculate the total cost for a plate/menu item."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Get plate info
            cursor.execute("SELECT name, category, description FROM plates WHERE name = ?", (plate_name,))
            plate_data = cursor.fetchone()
            if not plate_data:
                raise ValueError(f"Plate '{plate_name}' not found")

            # Get plate ingredients with their costs
            cursor.execute("""
                SELECT pi.ingredient_name, pi.quantity, pi.unit,
                       i.cost_per_recipe_unit, i.recipe_unit
                FROM plate_ingredients pi
                JOIN ingredients i ON pi.ingredient_name = i.name
                WHERE pi.plate_name = ?
            """, (plate_name,))

            ingredients = cursor.fetchall()
            ingredient_costs = []
            total_ingredient_cost = 0

            for ing_data in ingredients:
                ing_name, quantity, unit, cost_per_recipe_unit, recipe_unit = ing_data

                try:
                    # Convert quantity to recipe unit for cost calculation
                    if unit != recipe_unit:
                        converted_quantity = self.converter.convert(quantity, unit, recipe_unit)
                    else:
                        converted_quantity = quantity

                    # Calculate cost (cost_per_recipe_unit already includes yield)
                    ingredient_cost = converted_quantity * cost_per_recipe_unit

                    # Round up sub-cent costs to $0.01 minimum
                    if ingredient_cost > 0 and ingredient_cost < 0.01:
                        rounded_cost = 0.01
                    else:
                        rounded_cost = round(ingredient_cost, 2)

                    total_ingredient_cost += rounded_cost

                    ingredient_costs.append({
                        'name': ing_name,
                        'quantity': quantity,
                        'unit': unit,
                        'cost': rounded_cost
                    })

                except Exception as e:
                    print(f"Warning: Could not calculate cost for {ing_name}: {e}")
                    ingredient_costs.append({
                        'name': ing_name,
                        'quantity': quantity,
                        'unit': unit,
                        'cost': 0.0
                    })

            # NOTE: Recipe costs from plate_recipes table are calculated separately
            # in web_app.py to avoid double-counting. This function only returns
            # direct ingredient costs from plate_ingredients table.

            # Use default q_factor for plates
            q_factor = 0.04
            q_factor_cost = total_ingredient_cost * q_factor
            total_with_q = total_ingredient_cost + q_factor_cost

            return {
                'plate_name': plate_name,
                'category': plate_data[1],
                'description': plate_data[2],
                'ingredient_cost': round(total_ingredient_cost, 2),
                'q_factor': q_factor,
                'q_factor_cost': round(q_factor_cost, 2),
                'total_cost': round(total_with_q, 2),
                'ingredient_breakdown': ingredient_costs
            }


class RecipeManagementSystem:
    """Main RMS application class with CLI interface."""

    def __init__(self):
        self.db = DatabaseManager()
        self.commands = {
            '01': self.add_recipe,
            '02': self.list_recipes,
            '03': self.delete_recipe,
            '04': self.calculate_recipe_cost,
            '05': self.scale_recipe,
            '11': self.add_ingredient,
            '12': self.list_ingredients,
            '13': self.search_ingredients,
            '14': self.update_ingredient,
            '21': self.add_recipe_ingredient,
            '22': self.show_recipe_ingredients,
            '23': self.remove_recipe_ingredient,
            '31': self.import_legacy_data,
            '99': self.show_help
        }

    def run(self):
        """Main application loop."""
        print("🍳 Modern Recipe Management System v2.0")
        print("=" * 50)
        self.show_help()

        while True:
            try:
                command = input("\n📋 Enter command (99 for help, 'quit' to exit): ").strip()

                if command.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break

                if command in self.commands:
                    self.commands[command]()
                else:
                    print("❌ Invalid command. Type '99' for help.")

            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")

    def show_help(self):
        """Display available commands."""
        help_text = """
📖 Available Commands:
┌─────────────────────────────────────────────────────────────┐
│ RECIPES                                                     │
│ 01 - Add new recipe           02 - List all recipes        │
│ 03 - Delete recipe            04 - Calculate recipe cost   │
│ 05 - Scale recipe for events                               │
│                                                             │
│ INGREDIENTS                                                 │
│ 11 - Add new ingredient       12 - List ingredients        │
│ 13 - Search ingredients       14 - Update ingredient       │
│                                                             │
│ RECIPE INGREDIENTS                                          │
│ 21 - Add ingredient to recipe 22 - Show recipe ingredients │
│ 23 - Remove ingredient from recipe                         │
│                                                             │
│ DATA MANAGEMENT                                             │
│ 31 - Import legacy JSON data                               │
│                                                             │
│ HELP                                                        │
│ 99 - Show this help menu                                   │
└─────────────────────────────────────────────────────────────┘
        """
        print(help_text)

    def add_recipe(self):
        """Add a new recipe."""
        print("\n🆕 Add New Recipe")
        name = input("Recipe name: ").strip()
        if not name:
            print("❌ Recipe name cannot be empty")
            return

        try:
            servings = int(input("Number of servings: "))
            description = input("Description (optional): ").strip()
            prep_time = int(input("Prep time in minutes (0 for unknown): ") or "0")
            cook_time = int(input("Cook time in minutes (0 for unknown): ") or "0")
            q_factor = float(input("Q-factor (default 0.04): ") or "0.04")

            recipe = Recipe(name, servings, q_factor, description, prep_time, cook_time)

            if self.db.add_recipe(recipe):
                print(f"✅ Recipe '{name}' added successfully!")
            else:
                print(f"❌ Recipe '{name}' already exists")

        except ValueError:
            print("❌ Invalid input. Please enter numeric values where required.")

    def list_recipes(self):
        """List all recipes."""
        recipes = self.db.get_recipes()
        if not recipes:
            print("📭 No recipes found")
            return

        print(f"\n📚 Found {len(recipes)} recipes:")

        table_data = []
        for recipe in recipes:
            total_time = recipe.prep_time + recipe.cook_time
            time_str = f"{total_time}m" if total_time > 0 else "Unknown"
            table_data.append([
                recipe.name,
                recipe.servings,
                f"{recipe.q_factor:.1%}",
                time_str,
                recipe.description[:50] + "..." if len(recipe.description) > 50 else recipe.description
            ])

        print(tabulate(table_data,
                      headers=["Recipe", "Servings", "Q-Factor", "Time", "Description"],
                      tablefmt="grid"))

    def calculate_recipe_cost(self):
        """Calculate and display recipe cost."""
        recipe_name = input("Recipe name: ").strip()
        if not recipe_name:
            print("❌ Recipe name cannot be empty")
            return

        try:
            cost_data = self.db.calculate_recipe_cost(recipe_name)

            print(f"\n💰 Cost Analysis for '{recipe_name}'")
            print("=" * 50)
            print(f"Servings: {cost_data['servings']}")
            print(f"Ingredient Cost: ${cost_data['ingredient_cost']:.2f}")
            print(f"Q-Factor ({cost_data['q_factor']:.1%}): ${cost_data['q_factor_cost']:.2f}")
            print(f"Total Cost: ${cost_data['total_cost']:.2f}")
            print(f"Cost per Serving: ${cost_data['cost_per_serving']:.2f}")

            print("\n📋 Ingredient Breakdown:")
            table_data = []
            for item in cost_data['ingredient_breakdown']:
                table_data.append([
                    item['name'],
                    f"{item['quantity']} {item['unit']}",
                    f"${item['cost']:.2f}"
                ])

            print(tabulate(table_data,
                          headers=["Ingredient", "Quantity", "Cost"],
                          tablefmt="grid"))

        except ValueError as e:
            print(f"❌ {e}")

    def add_ingredient(self):
        """Add a new ingredient."""
        print("\n🥕 Add New Ingredient")
        name = input("Ingredient name: ").strip().title()
        if not name:
            print("❌ Ingredient name cannot be empty")
            return

        category = input("Category: ").strip().lower()

        try:
            unit_price = float(input("Unit price ($): "))
            purchase_unit = input("Purchase unit (e.g., lb, gal): ").strip()
            on_hand = float(input("Quantity available: "))
            conversion_density = float(input("Conversion density: "))
            base_unit = input("Base unit for recipes: ").strip()
            yield_percent = float(input("Yield percentage (default 95): ") or "95")

            ingredient = Ingredient(
                id=0,  # Auto-generated
                name=name,
                category=category,
                unit_price=unit_price,
                purchase_unit=purchase_unit,
                on_hand=on_hand,
                conversion_density=conversion_density,
                base_unit=base_unit,
                yield_percent=yield_percent
            )

            if self.db.add_ingredient(ingredient):
                print(f"✅ Ingredient '{name}' added successfully!")
            else:
                print(f"❌ Ingredient '{name}' already exists")

        except ValueError:
            print("❌ Invalid input. Please enter numeric values where required.")

    def list_ingredients(self):
        """List all ingredients."""
        ingredients = self.db.get_ingredients()
        if not ingredients:
            print("📭 No ingredients found")
            return

        print(f"\n🥘 Found {len(ingredients)} ingredients:")

        table_data = []
        for ing in ingredients:
            adjusted_price = ing.unit_price / ing.on_hand * ing.conversion_density
            table_data.append([
                ing.name,
                ing.category.title(),
                f"${ing.unit_price:.2f}",
                ing.purchase_unit,
                f"${adjusted_price:.3f}",
                ing.base_unit,
                f"{ing.yield_percent:.1f}%"
            ])

        print(tabulate(table_data,
                      headers=["Ingredient", "Category", "Unit Price", "P.Unit", "Adj.Price", "Base Unit", "Yield"],
                      tablefmt="grid"))

    def add_recipe_ingredient(self):
        """Add an ingredient to a recipe."""
        recipe_name = input("Recipe name: ").strip()
        ingredient_name = input("Ingredient name: ").strip().title()

        try:
            quantity = float(input("Quantity: "))
            unit = input("Unit: ").strip()

            recipe_ingredient = RecipeIngredient(recipe_name, ingredient_name, quantity, unit)

            if self.db.add_recipe_ingredient(recipe_ingredient):
                print(f"✅ Added {quantity} {unit} of {ingredient_name} to {recipe_name}")
            else:
                print("❌ Failed to add ingredient to recipe")

        except ValueError:
            print("❌ Invalid quantity")

    def show_recipe_ingredients(self):
        """Show all ingredients in a recipe."""
        recipe_name = input("Recipe name: ").strip()
        ingredients = self.db.get_recipe_ingredients(recipe_name)

        if not ingredients:
            print(f"📭 No ingredients found for recipe '{recipe_name}'")
            return

        print(f"\n🍲 Ingredients in '{recipe_name}':")
        table_data = []
        for ing in ingredients:
            table_data.append([ing.ingredient_name, f"{ing.quantity} {ing.unit}"])

        print(tabulate(table_data, headers=["Ingredient", "Quantity"], tablefmt="grid"))

    def scale_recipe(self):
        """Scale a recipe for different serving sizes."""
        recipe_name = input("Recipe name: ").strip()
        try:
            new_servings = int(input("New number of servings: "))
            cost_data = self.db.calculate_recipe_cost(recipe_name)

            scale_factor = new_servings / cost_data['servings']
            scaled_cost = cost_data['total_cost'] * scale_factor

            print(f"\n📏 Scaled Recipe: '{recipe_name}' for {new_servings} servings")
            print(f"Scale Factor: {scale_factor:.2f}x")
            print(f"Total Cost: ${scaled_cost:.2f}")
            print(f"Cost per Serving: ${scaled_cost / new_servings:.2f}")

        except (ValueError, KeyError) as e:
            print(f"❌ Error scaling recipe: {e}")

    def import_legacy_data(self):
        """Import data from legacy JSON files."""
        json_file = input("JSON file path (or 'aladdin' for default): ").strip()

        if json_file == 'aladdin':
            json_file = 'rms/00_ingredients_aladdin.json'

        if not os.path.exists(json_file):
            print(f"❌ File '{json_file}' not found")
            return

        try:
            with open(json_file, 'r') as f:
                data = json.load(f)

            imported_count = 0
            for category, items in data.items():
                for item in items:
                    ingredient = Ingredient(
                        id=0,
                        name=item.get('Ingredient', '').title(),
                        category=category,
                        unit_price=float(item.get('UP', 0)),
                        purchase_unit=item.get('UA', ''),
                        on_hand=float(item.get('QA', 1)),
                        conversion_density=float(item.get('CD', 1)),
                        base_unit=item.get('UB', ''),
                        yield_percent=95.0
                    )

                    if self.db.add_ingredient(ingredient):
                        imported_count += 1

            print(f"✅ Imported {imported_count} ingredients from {json_file}")

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"❌ Error importing data: {e}")

    def search_ingredients(self):
        """Search for ingredients by name."""
        keyword = input("Search keyword: ").strip().lower()
        ingredients = self.db.get_ingredients()

        matches = [ing for ing in ingredients if keyword in ing.name.lower()]

        if not matches:
            print(f"🔍 No ingredients found matching '{keyword}'")
            return

        print(f"\n🔍 Found {len(matches)} ingredients matching '{keyword}':")
        table_data = []
        for ing in matches:
            table_data.append([ing.name, ing.category.title(), f"${ing.unit_price:.2f}", ing.purchase_unit])

        print(tabulate(table_data, headers=["Ingredient", "Category", "Price", "Unit"], tablefmt="grid"))

    def delete_recipe(self):
        """Delete a recipe (placeholder)."""
        print("🚧 Delete recipe feature coming soon!")

    def remove_recipe_ingredient(self):
        """Remove ingredient from recipe (placeholder)."""
        print("🚧 Remove recipe ingredient feature coming soon!")

    def update_ingredient(self):
        """Update ingredient information (placeholder)."""
        print("🚧 Update ingredient feature coming soon!")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Modern Recipe Management System")
    parser.add_argument('--version', action='version', version='RMS 2.0')
    parser.add_argument('--db', default='rms_unified.db', help='Database file path')

    args = parser.parse_args()

    # Initialize and run the application
    rms = RecipeManagementSystem()
    rms.run()


if __name__ == "__main__":
    main()