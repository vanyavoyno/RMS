#!/usr/bin/env python3
"""
Modern Web-Based Recipe Management System
A user-friendly Flask web application for managing recipes and ingredients
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from pathlib import Path
import json
from rms_modern import DatabaseManager, Recipe, Ingredient, RecipeIngredient, Plate, PlateIngredient

app = Flask(__name__)
app.secret_key = 'rms_secret_key_2024'

# Database setup
DB_PATH = Path(__file__).parent / "rms_unified.db"
db_manager = DatabaseManager(str(DB_PATH))

@app.route('/')
def dashboard():
    """Main dashboard page."""
    ingredients = db_manager.get_ingredients()
    recipes = db_manager.get_recipes()

    # Get some statistics
    stats = {
        'total_ingredients': len(ingredients),
        'total_recipes': len(recipes),
        'categories': len(set(ing.category for ing in ingredients)),
        'avg_recipe_servings': round(sum(r.servings for r in recipes) / len(recipes), 1) if recipes else 0
    }

    # Recent recipes (last 5)
    recent_recipes = recipes[:5] if recipes else []

    return render_template('dashboard.html', stats=stats, recent_recipes=recent_recipes)

@app.route('/recipes')
def recipes():
    """Recipe listing page."""
    all_recipes = db_manager.get_recipes()
    return render_template('recipes.html', recipes=all_recipes)

@app.route('/recipe/<path:recipe_name>')
def recipe_detail(recipe_name):
    """Recipe detail page."""
    recipes = db_manager.get_recipes()
    recipe = next((r for r in recipes if r.name == recipe_name), None)

    if not recipe:
        flash(f"Recipe '{recipe_name}' not found", 'error')
        return redirect(url_for('recipes'))

    # Get recipe ingredients with on_hand quantities
    recipe_ingredients = db_manager.get_recipe_ingredients(recipe_name)

    # Get ingredient on_hand quantities
    all_ingredients = db_manager.get_ingredients()
    ingredient_lookup = {ing.name: ing.on_hand for ing in all_ingredients}

    # Add on_hand data to recipe ingredients
    for recipe_ing in recipe_ingredients:
        recipe_ing.on_hand = ingredient_lookup.get(recipe_ing.ingredient_name, 0)

    # Calculate cost
    try:
        cost_data = db_manager.calculate_recipe_cost(recipe_name)
    except Exception as e:
        cost_data = None
        flash(f"Could not calculate cost: {str(e)}", 'warning')

    # Get allergens
    allergens = db_manager.get_recipe_allergens(recipe_name)
    allergen_details = []
    for allergen_code in sorted(allergens):
        info = db_manager.get_allergen_info(allergen_code)
        if info:
            allergen_details.append(info)

    return render_template('recipe_detail.html',
                         recipe=recipe,
                         recipe_ingredients=recipe_ingredients,
                         cost_data=cost_data,
                         allergens=allergen_details)

@app.route('/ingredients')
def ingredients():
    """Ingredients listing page."""
    import sqlite3

    search = request.args.get('search', '')
    category = request.args.get('category', '')

    all_ingredients = db_manager.get_ingredients()

    # Check which ingredients are used in recipes or plates
    with sqlite3.connect(str(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT i.name,
                   CASE WHEN (ri.ingredient_name IS NOT NULL OR pi.ingredient_name IS NOT NULL)
                        THEN 1 ELSE 0 END as is_used
            FROM ingredients i
            LEFT JOIN recipe_ingredients ri ON i.name = ri.ingredient_name
            LEFT JOIN plate_ingredients pi ON i.name = pi.ingredient_name
            GROUP BY i.name
        """)
        usage_map = {row[0]: row[1] for row in cursor.fetchall()}

    # Add is_used attribute to ingredients
    for ing in all_ingredients:
        ing.is_used = usage_map.get(ing.name, 0)

    # Filter by search term
    if search:
        all_ingredients = [ing for ing in all_ingredients
                          if search.lower() in ing.name.lower()]

    # Filter by category
    if category:
        all_ingredients = [ing for ing in all_ingredients
                          if ing.category.lower() == category.lower()]

    # Get all categories for filter dropdown
    all_categories = sorted(set(ing.category for ing in db_manager.get_ingredients()))

    return render_template('ingredients.html',
                         ingredients=all_ingredients,
                         categories=all_categories,
                         current_search=search,
                         current_category=category)

@app.route('/ingredients/bulk')
def ingredients_bulk():
    """Bulk inventory management page."""
    import sqlite3

    ingredients_by_category = db_manager.get_ingredients_by_category()
    total_ingredients = sum(len(ingredients) for ingredients in ingredients_by_category.values())

    # Check which ingredients are used in recipes or plates
    with sqlite3.connect(str(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT i.name,
                   CASE WHEN (ri.ingredient_name IS NOT NULL OR pi.ingredient_name IS NOT NULL)
                        THEN 1 ELSE 0 END as is_used
            FROM ingredients i
            LEFT JOIN recipe_ingredients ri ON i.name = ri.ingredient_name
            LEFT JOIN plate_ingredients pi ON i.name = pi.ingredient_name
            GROUP BY i.name
        """)
        usage_map = {row[0]: row[1] for row in cursor.fetchall()}

    # Add is_used attribute to all ingredients
    for category, ingredients in ingredients_by_category.items():
        for ing in ingredients:
            ing.is_used = usage_map.get(ing.name, 0)

    return render_template('ingredients_bulk.html',
                         ingredients_by_category=ingredients_by_category,
                         total_ingredients=total_ingredients)

@app.route('/api/update_ingredient_price', methods=['POST'])
def api_update_ingredient_price():
    """API endpoint to update ingredient purchase price (deprecated - use update_ingredient instead)."""
    try:
        ingredient_id = int(request.form['ingredient_id'])
        purchase_price = float(request.form.get('purchase_price', request.form.get('bulk_price', 0)))

        # Simple price update - recalculate all costs
        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # Get current ingredient data
            cursor.execute("""
                SELECT units_per_purchase, recipe_units_per_inventory, yield_percent
                FROM ingredients WHERE id = ?
            """, (ingredient_id,))
            result = cursor.fetchone()

            if result:
                units_per_purchase, recipe_units_per_inventory, yield_percent = result

                # Recalculate costs
                cost_per_inventory_unit = purchase_price / units_per_purchase if units_per_purchase > 0 else 0
                cost_per_recipe_unit = (cost_per_inventory_unit / recipe_units_per_inventory) / (yield_percent / 100.0) if recipe_units_per_inventory > 0 else 0

                # Update
                cursor.execute("""
                    UPDATE ingredients
                    SET purchase_price = ?, cost_per_inventory_unit = ?, cost_per_recipe_unit = ?
                    WHERE id = ?
                """, (purchase_price, cost_per_inventory_unit, cost_per_recipe_unit, ingredient_id))
                conn.commit()

                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': 'Ingredient not found'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/update_ingredient', methods=['POST'])
def api_update_ingredient():
    """API endpoint to update all ingredient fields."""
    try:
        # Log what we received for debugging
        print(f"Form data received: {dict(request.form)}")

        # Validate required fields
        ingredient_id = request.form.get('ingredient_id')
        if not ingredient_id:
            return jsonify({'success': False, 'error': 'Missing ingredient_id'}), 400
        ingredient_id = int(ingredient_id)

        new_name = request.form.get('name', '').strip()
        original_name = request.form.get('original_name', '').strip()

        if not new_name:
            return jsonify({'success': False, 'error': 'Missing ingredient name'}), 400

        category = request.form.get('category')
        if not category:
            return jsonify({'success': False, 'error': 'Missing category'}), 400

        supplier = request.form.get('supplier', '')

        # Purchase level
        purchase_unit = request.form.get('purchase_unit')
        if not purchase_unit:
            return jsonify({'success': False, 'error': 'Missing purchase_unit'}), 400

        purchase_price = request.form.get('purchase_price')
        if not purchase_price:
            return jsonify({'success': False, 'error': 'Missing purchase_price'}), 400
        purchase_price = float(purchase_price)

        # Inventory level
        inventory_unit = request.form.get('inventory_unit')
        if not inventory_unit:
            return jsonify({'success': False, 'error': 'Missing inventory_unit'}), 400

        units_per_purchase = request.form.get('units_per_purchase')
        if not units_per_purchase:
            return jsonify({'success': False, 'error': 'Missing units_per_purchase'}), 400
        units_per_purchase = float(units_per_purchase)

        # Recipe level
        recipe_unit = request.form.get('recipe_unit')
        if not recipe_unit:
            return jsonify({'success': False, 'error': 'Missing recipe_unit'}), 400

        recipe_units_per_inventory = request.form.get('recipe_units_per_inventory')
        if not recipe_units_per_inventory:
            return jsonify({'success': False, 'error': 'Missing recipe_units_per_inventory'}), 400
        recipe_units_per_inventory = float(recipe_units_per_inventory)

        on_hand = request.form.get('on_hand', '0')
        on_hand = float(on_hand)

        yield_percent = request.form.get('yield_percent', '95.0')
        yield_percent = float(yield_percent)

        # Get allergens from checkboxes (returns list)
        allergens_list = request.form.getlist('allergens')
        allergens_str = ','.join(allergens_list) if allergens_list else ''

        print(f"Allergens received: {allergens_list} -> {allergens_str}")

        # Calculate costs
        cost_per_inventory_unit = purchase_price / units_per_purchase if units_per_purchase > 0 else 0
        cost_per_recipe_unit = (cost_per_inventory_unit / recipe_units_per_inventory) / (yield_percent / 100.0) if recipe_units_per_inventory > 0 else 0

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # If name changed, update all foreign key references first
            if new_name != original_name and original_name:
                # Update recipe_ingredients references
                cursor.execute("""
                    UPDATE recipe_ingredients
                    SET ingredient_name = ?
                    WHERE ingredient_name = ?
                """, (new_name, original_name))

                # Update plate_ingredients references
                cursor.execute("""
                    UPDATE plate_ingredients
                    SET ingredient_name = ?
                    WHERE ingredient_name = ?
                """, (new_name, original_name))

                print(f"Updated ingredient name from '{original_name}' to '{new_name}'")

            # Update the ingredient itself
            cursor.execute("""
                UPDATE ingredients
                SET name = ?, category = ?, supplier = ?,
                    purchase_unit = ?, purchase_price = ?,
                    inventory_unit = ?, units_per_purchase = ?, cost_per_inventory_unit = ?,
                    recipe_unit = ?, recipe_units_per_inventory = ?, yield_percent = ?, cost_per_recipe_unit = ?,
                    on_hand = ?, allergens = ?
                WHERE id = ?
            """, (new_name, category, supplier,
                  purchase_unit, purchase_price,
                  inventory_unit, units_per_purchase, cost_per_inventory_unit,
                  recipe_unit, recipe_units_per_inventory, yield_percent, cost_per_recipe_unit,
                  on_hand, allergens_str, ingredient_id))
            conn.commit()

        return jsonify({'success': True, 'allergens': allergens_str, 'new_name': new_name})

    except KeyError as e:
        return jsonify({'success': False, 'error': f'Missing field: {str(e)}'}), 400
    except ValueError as e:
        return jsonify({'success': False, 'error': f'Invalid value: {str(e)}'}), 400
    except Exception as e:
        import traceback
        print(f"Error in update_ingredient: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'Server error: {str(e)}'}), 500

@app.route('/api/update_ingredient_stock', methods=['POST'])
def api_update_ingredient_stock():
    """API endpoint to update ingredient stock quantity."""
    try:
        ingredient_id = int(request.form['ingredient_id'])
        quantity = float(request.form['quantity'])

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE ingredients SET on_hand = ? WHERE id = ?",
                         (quantity, ingredient_id))
            conn.commit()

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/add_recipe', methods=['GET', 'POST'])
def add_recipe():
    """Add new recipe page."""
    if request.method == 'POST':
        try:
            recipe = Recipe(
                name=request.form['name'],
                servings=int(request.form['servings']),
                q_factor=float(request.form.get('q_factor', 0.04)),
                description=request.form.get('description', ''),
                prep_time=int(request.form.get('prep_time', 0)),
                cook_time=int(request.form.get('cook_time', 0)),
                instructions=request.form.get('instructions', ''),
                whole_unit='whole_unit' in request.form
            )

            if db_manager.add_recipe(recipe):
                flash(f"Recipe '{recipe.name}' added successfully!", 'success')
                return redirect(url_for('recipe_detail', recipe_name=recipe.name))
            else:
                flash(f"Recipe '{recipe.name}' already exists!", 'error')

        except Exception as e:
            flash(f"Error adding recipe: {str(e)}", 'error')

    return render_template('add_recipe.html')

@app.route('/add_ingredient', methods=['GET', 'POST'])
def add_ingredient():
    """Add new ingredient page."""
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form['name'].title()
            category = request.form['category'].title()
            supplier = request.form.get('supplier', '').strip()

            # Purchase level
            purchase_unit = request.form['purchase_unit']
            purchase_price = float(request.form['purchase_price'])

            # Inventory level
            inventory_unit = request.form['inventory_unit']
            units_per_purchase = float(request.form['units_per_purchase'])
            on_hand = float(request.form.get('on_hand', 0))

            # Recipe level
            recipe_unit = request.form['recipe_unit']
            recipe_units_per_inventory = float(request.form['recipe_units_per_inventory'])
            yield_percent = float(request.form.get('yield_percent', 95.0))

            # Calculate costs
            cost_per_inventory_unit = purchase_price / units_per_purchase if units_per_purchase > 0 else 0
            cost_per_recipe_unit = (cost_per_inventory_unit / recipe_units_per_inventory) / (yield_percent / 100.0) if recipe_units_per_inventory > 0 else 0

            # Get allergens from checkboxes
            allergens_list = request.form.getlist('allergens')
            allergens_str = ','.join(allergens_list) if allergens_list else ''

            # Insert into database
            import sqlite3
            with sqlite3.connect(db_manager.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO ingredients (
                        name, category, purchase_unit, purchase_price,
                        inventory_unit, units_per_purchase, cost_per_inventory_unit,
                        on_hand, par_level,
                        recipe_unit, recipe_units_per_inventory, yield_percent, cost_per_recipe_unit,
                        supplier, allergens
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    name, category, purchase_unit, purchase_price,
                    inventory_unit, units_per_purchase, cost_per_inventory_unit,
                    on_hand, 0,  # par_level default
                    recipe_unit, recipe_units_per_inventory, yield_percent, cost_per_recipe_unit,
                    supplier, allergens_str
                ))
                conn.commit()

            flash(f"Ingredient '{name}' added successfully!", 'success')
            return redirect(url_for('ingredients'))

        except sqlite3.IntegrityError:
            flash(f"Ingredient '{name}' already exists!", 'error')
        except Exception as e:
            flash(f"Error adding ingredient: {str(e)}", 'error')
            import traceback
            print(traceback.format_exc())

    # Get existing categories for dropdown
    import sqlite3
    with sqlite3.connect(db_manager.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM ingredients ORDER BY category")
        categories = [row[0] for row in cursor.fetchall()]

    # Add default categories if none exist
    if not categories:
        categories = [
            "Bar Supplies", "Bread", "Canned Goods", "Dairy and Eggs", "Dry Goods",
            "Frozen", "Meats & Proteins", "Miscellaneous", "Nuts and Seeds",
            "Oils and Vinegars", "Produce", "Readymade", "Spices and Seasonings"
        ]

    return render_template('add_ingredient.html', categories=categories)

@app.route('/api/search_ingredients')
def api_search_ingredients():
    """API endpoint for ingredient search (includes both ingredients and recipes)."""
    query = request.args.get('q', '').lower()
    ingredients = db_manager.get_ingredients()
    recipes = db_manager.get_recipes()

    # Search ingredients
    ingredient_matches = [
        {
            'id': ing.id,
            'name': ing.name,
            'category': ing.category,
            'unit_price': ing.cost_per_recipe_unit,
            'recipe_unit': ing.recipe_unit,
            'type': 'ingredient'
        }
        for ing in ingredients
        if query in ing.name.lower()
    ]

    # Search recipes (sub-recipes/preparations)
    recipe_matches = [
        {
            'id': None,
            'name': recipe.name,
            'category': 'Preparation',
            'unit_price': 0,
            'recipe_unit': 'ea',
            'type': 'recipe'
        }
        for recipe in recipes
        if query in recipe.name.lower()
    ]

    # Combine and sort by name
    all_matches = ingredient_matches + recipe_matches
    all_matches.sort(key=lambda x: x['name'])

    return jsonify(all_matches[:10])  # Limit to 10 results

@app.route('/api/recipe_cost/<path:recipe_name>')
def api_recipe_cost(recipe_name):
    """API endpoint for recipe cost calculation."""
    try:
        cost_data = db_manager.calculate_recipe_cost(recipe_name)
        return jsonify(cost_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/update_recipe_ingredient', methods=['POST'])
def api_update_recipe_ingredient():
    """API endpoint for updating recipe ingredients."""
    try:
        data = request.get_json()
        recipe_name = data.get('recipe_name')
        ingredient_name = data.get('ingredient_name')
        action = data.get('action')

        if not recipe_name or not ingredient_name or not action:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        if action == 'add':
            quantity = data.get('quantity')
            unit = data.get('unit')
            if not quantity or not unit:
                return jsonify({'success': False, 'error': 'Missing quantity or unit'}), 400

            cursor.execute("""
                INSERT OR REPLACE INTO recipe_ingredients
                (recipe_name, ingredient_name, quantity, unit)
                VALUES (?, ?, ?, ?)
            """, (recipe_name, ingredient_name, quantity, unit))

        elif action == 'remove':
            cursor.execute("""
                DELETE FROM recipe_ingredients
                WHERE recipe_name = ? AND ingredient_name = ?
            """, (recipe_name, ingredient_name))

        elif action == 'update_quantity':
            quantity = data.get('quantity')
            if quantity is None:
                return jsonify({'success': False, 'error': 'Missing quantity'}), 400

            cursor.execute("""
                UPDATE recipe_ingredients
                SET quantity = ?
                WHERE recipe_name = ? AND ingredient_name = ?
            """, (quantity, recipe_name, ingredient_name))

        elif action == 'update_unit':
            unit = data.get('unit')
            if not unit:
                return jsonify({'success': False, 'error': 'Missing unit'}), 400

            cursor.execute("""
                UPDATE recipe_ingredients
                SET unit = ?
                WHERE recipe_name = ? AND ingredient_name = ?
            """, (unit, recipe_name, ingredient_name))

        else:
            return jsonify({'success': False, 'error': 'Invalid action'}), 400

        conn.commit()
        conn.close()

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/recipe/<path:recipe_name>/add_ingredient', methods=['GET', 'POST'])
def add_ingredient_to_recipe(recipe_name):
    """Add ingredient to recipe."""
    if request.method == 'POST':
        try:
            recipe_ingredient = RecipeIngredient(
                recipe_name=recipe_name,
                ingredient_name=request.form['ingredient_name'],
                quantity=float(request.form['quantity']),
                unit=request.form['unit']
            )

            if db_manager.add_recipe_ingredient(recipe_ingredient):
                flash(f"Added {recipe_ingredient.quantity} {recipe_ingredient.unit} of {recipe_ingredient.ingredient_name} to {recipe_name}", 'success')
            else:
                flash(f"Failed to add ingredient. It may already exist in this recipe.", 'error')

            return redirect(url_for('recipe_detail', recipe_name=recipe_name))

        except Exception as e:
            flash(f"Error adding ingredient: {str(e)}", 'error')

    return render_template('add_ingredient_to_recipe.html', recipe_name=recipe_name)

@app.route('/recipe/<path:recipe_name>/edit', methods=['GET', 'POST'])
def edit_recipe(recipe_name):
    """Edit an existing recipe."""
    recipes = db_manager.get_recipes()
    recipe = next((r for r in recipes if r.name == recipe_name), None)

    if not recipe:
        flash(f"Recipe '{recipe_name}' not found", 'error')
        return redirect(url_for('recipes'))

    if request.method == 'POST':
        try:
            updated_recipe = Recipe(
                name=request.form['name'],
                servings=int(request.form['servings']),
                q_factor=float(request.form.get('q_factor', 0.04)),
                description=request.form.get('description', ''),
                prep_time=int(request.form.get('prep_time', 0)),
                cook_time=int(request.form.get('cook_time', 0)),
                instructions=request.form.get('instructions', ''),
                whole_unit='whole_unit' in request.form
            )

            if db_manager.update_recipe(recipe_name, updated_recipe):
                flash(f"Recipe '{updated_recipe.name}' updated successfully!", 'success')
                return redirect(url_for('recipe_detail', recipe_name=updated_recipe.name))
            else:
                flash(f"Failed to update recipe. Name might already exist.", 'error')

        except Exception as e:
            flash(f"Error updating recipe: {str(e)}", 'error')

    # Get recipe ingredients and all available ingredients
    recipe_ingredients = db_manager.get_recipe_ingredients(recipe_name)
    all_ingredients = db_manager.get_ingredients()

    return render_template('edit_recipe.html',
                         recipe=recipe,
                         recipe_ingredients=recipe_ingredients,
                         all_ingredients=all_ingredients)

@app.route('/recipe/<path:recipe_name>/delete', methods=['POST'])
def delete_recipe(recipe_name):
    """Delete a recipe."""
    try:
        # Note: This is a simple implementation. In production, you'd want more sophisticated deletion
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        # Delete recipe ingredients first (foreign key constraint)
        cursor.execute("DELETE FROM recipe_ingredients WHERE recipe_name = ?", (recipe_name,))

        # Delete the recipe
        cursor.execute("DELETE FROM recipes WHERE name = ?", (recipe_name,))

        conn.commit()
        conn.close()

        flash(f"Recipe '{recipe_name}' has been deleted successfully.", 'success')
        return redirect(url_for('recipes'))

    except Exception as e:
        flash(f"Error deleting recipe: {str(e)}", 'error')
        return redirect(url_for('recipe_detail', recipe_name=recipe_name))

def scale_instructions(original_instructions, scaled_ingredients, scale_factor):
    """Scale ingredient quantities mentioned in recipe instructions."""
    if not original_instructions:
        return ""

    scaled_instructions = original_instructions

    # Create a mapping of ingredient names to their scaled quantities
    ingredient_mapping = {}
    for ing in scaled_ingredients:
        ingredient_mapping[ing['name'].lower()] = {
            'original': ing['original_quantity'],
            'scaled': ing['scaled_quantity'],
            'unit': ing['unit']
        }


    import re

    # Look for quantity patterns with comprehensive unit support
    quantity_patterns = [
        # Fractions and decimals with volume units
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(pinches?|pinch)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(dashes?|dash)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(teaspoons?|tsp|t)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(tablespoons?|tbsp|T)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(fl\.?oz\.?|fluid\s+ounces?)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(cups?|cup|c)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(pints?|pt)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(quarts?|qt)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(gallons?|gal)\s+(?:of\s+)?(\w+)',

        # Weight units
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(ounces?|oz)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(pounds?|lbs?|lb)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(grams?|g)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(kilograms?|kg)\s+(?:of\s+)?(\w+)',

        # Count units
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(cloves?)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(bunches?|bunch)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(slices?|slice)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(loaves?|loaf)\s+(?:of\s+)?(\w+)',
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s*(dozens?|doz)\s+(?:of\s+)?(\w+)',

        # Simple quantity with ingredient (like "6 apples", "2 eggs")
        r'(\d+\/\d+|\d+(?:\.\d+)?)\s+(\w+)(?=\s|,|\.|\n|$)',
    ]

    for pattern in quantity_patterns:
        matches = re.findall(pattern, scaled_instructions, re.IGNORECASE)
        for match in matches:
            if len(match) >= 2:
                original_qty_str = match[0]

                # Handle different pattern structures
                if len(match) == 2:
                    # Simple patterns like "6 apples" - no unit
                    unit = ""
                    ingredient = match[1].lower()
                else:
                    # Complex patterns with units like "3/4 cup sugar"
                    unit = match[1] if len(match) > 2 else ""
                    ingredient = match[2].lower() if len(match) > 2 else match[1].lower()

                # Check if this ingredient is in our recipe (handle plurals and case)
                matched_ingredient = None
                ingredient_lower = ingredient.lower()

                # Direct match
                if ingredient_lower in ingredient_mapping:
                    matched_ingredient = ingredient_lower
                else:
                    # Try to match against all ingredient names with plural handling
                    for ing_name in ingredient_mapping.keys():
                        ing_lower = ing_name.lower()
                        # Check if ingredient matches (with s/es removal for plurals)
                        if (ingredient_lower == ing_lower or
                            ingredient_lower == ing_lower + 's' or
                            ingredient_lower == ing_lower + 'es' or
                            ingredient_lower + 's' == ing_lower or
                            ingredient_lower + 'es' == ing_lower):
                            matched_ingredient = ing_name
                            break

                if matched_ingredient:
                    try:
                        # Convert fraction to decimal if needed
                        if '/' in original_qty_str:
                            parts = original_qty_str.split('/')
                            original_qty = float(parts[0]) / float(parts[1])
                        else:
                            original_qty = float(original_qty_str)

                        # Scale the quantity
                        scaled_qty = original_qty * scale_factor

                        # Format scaled quantity nicely
                        if scaled_qty == int(scaled_qty):
                            scaled_qty_str = str(int(scaled_qty))
                        else:
                            scaled_qty_str = f"{scaled_qty:.2f}".rstrip('0').rstrip('.')

                        # Replace in instructions (keep original ingredient text case)
                        old_text = f"{original_qty_str} {unit} {ingredient}" if unit else f"{original_qty_str} {ingredient}"
                        new_text = f"{scaled_qty_str} {unit} {ingredient}" if unit else f"{scaled_qty_str} {ingredient}"

                        scaled_instructions = re.sub(
                            re.escape(old_text),
                            new_text,
                            scaled_instructions,
                            flags=re.IGNORECASE
                        )
                    except (ValueError, ZeroDivisionError):
                        continue

    return scaled_instructions

@app.route('/scale_recipe/<path:recipe_name>')
def scale_recipe(recipe_name):
    """Recipe scaling page."""
    servings = request.args.get('servings', type=int)

    if not servings:
        flash("Please specify number of servings", 'error')
        return redirect(url_for('recipe_detail', recipe_name=recipe_name))

    try:
        # Get original recipe data
        recipes = db_manager.get_recipes()
        recipe = next((r for r in recipes if r.name == recipe_name), None)

        if not recipe:
            flash(f"Recipe '{recipe_name}' not found", 'error')
            return redirect(url_for('recipes'))

        cost_data = db_manager.calculate_recipe_cost(recipe_name)

        # Handle whole unit recipes differently
        if recipe.whole_unit:
            # Calculate how many whole units (pies, cakes, etc.) are needed
            units_needed = (servings + cost_data['servings'] - 1) // cost_data['servings']  # Ceiling division
            actual_servings = units_needed * cost_data['servings']
            scale_factor = units_needed

            # Scale ingredients, then apply prep factor to scaled amount
            scaled_ingredient_cost = cost_data['ingredient_cost'] * scale_factor
            scaled_prep_cost = scaled_ingredient_cost * cost_data['prep_factor']
            scaled_total = scaled_ingredient_cost + scaled_prep_cost

            scaled_data = {
                'original_servings': cost_data['servings'],
                'new_servings': servings,
                'actual_servings': actual_servings,
                'units_needed': units_needed,
                'is_whole_unit': True,
                'scale_factor': scale_factor,
                'original_cost': cost_data['total_cost'],
                'scaled_ingredient_cost': round(scaled_ingredient_cost, 2),
                'prep_factor': cost_data['prep_factor'],
                'prep_factor_cost': round(scaled_prep_cost, 2),
                'scaled_cost': round(scaled_total, 2),
                'cost_per_serving': round(scaled_total / actual_servings, 2),
                'waste_servings': actual_servings - servings,
                'scaled_ingredients': []
            }
        else:
            # Normal scaling for recipes that can be smoothly scaled
            scale_factor = servings / cost_data['servings']

            # Scale ingredients, then apply prep factor to scaled amount
            scaled_ingredient_cost = cost_data['ingredient_cost'] * scale_factor
            scaled_prep_cost = scaled_ingredient_cost * cost_data['prep_factor']
            scaled_total = scaled_ingredient_cost + scaled_prep_cost

            scaled_data = {
                'original_servings': cost_data['servings'],
                'new_servings': servings,
                'is_whole_unit': False,
                'scale_factor': scale_factor,
                'original_cost': cost_data['total_cost'],
                'scaled_ingredient_cost': round(scaled_ingredient_cost, 2),
                'prep_factor': cost_data['prep_factor'],
                'prep_factor_cost': round(scaled_prep_cost, 2),
                'scaled_cost': round(scaled_total, 2),
                'cost_per_serving': round(scaled_total / servings, 2),
                'scaled_ingredients': []
            }

        # Scale ingredients
        recipe_ingredients = db_manager.get_recipe_ingredients(recipe_name)
        for ing in recipe_ingredients:
            scaled_quantity = round(ing.quantity * scale_factor, 2)
            scaled_data['scaled_ingredients'].append({
                'name': ing.ingredient_name,
                'original_quantity': ing.quantity,
                'scaled_quantity': scaled_quantity,
                'unit': ing.unit
            })

        # Scale instructions
        scaled_data['original_instructions'] = recipe.instructions
        scaled_data['scaled_instructions'] = scale_instructions(
            recipe.instructions,
            scaled_data['scaled_ingredients'],
            scale_factor
        )

        return render_template('scale_recipe.html',
                             recipe_name=recipe_name,
                             recipe=recipe,
                             scaled_data=scaled_data,
                             cost_data=cost_data)

    except Exception as e:
        flash(f"Error scaling recipe: {str(e)}", 'error')
        return redirect(url_for('recipe_detail', recipe_name=recipe_name))

# PLATE/MENU MANAGEMENT ROUTES

@app.route('/plates')
def plates():
    """Show all plates/menu items."""
    import sqlite3
    with sqlite3.connect(db_manager.db_path) as conn:
        cursor = conn.cursor()

        # Get active plates ordered by display_order within categories
        cursor.execute("""
            SELECT name, category, description, display_order
            FROM plates
            WHERE is_active = 1
            ORDER BY display_order
        """)

        plates_data = cursor.fetchall()

        # Get category order
        cursor.execute("""
            SELECT name FROM plate_categories
            ORDER BY display_order
        """)
        menu_order = [row[0] for row in cursor.fetchall()]

    # Group plates by category maintaining order and add allergens
    categories = {}
    for plate_row in plates_data:
        plate_name = plate_row[0]
        # Get allergens for this plate
        allergens = db_manager.get_plate_allergens(plate_name)
        allergen_icons = []
        for allergen_code in sorted(allergens):
            info = db_manager.get_allergen_info(allergen_code)
            if info:
                allergen_icons.append(info['icon'])

        plate_dict = {
            'name': plate_name,
            'category': plate_row[1],
            'description': plate_row[2],
            'display_order': plate_row[3],
            'allergens': ' '.join(allergen_icons) if allergen_icons else ''
        }
        category = plate_row[1]
        if category not in categories:
            categories[category] = []
        categories[category].append(plate_dict)

    # Create ordered categories dictionary
    ordered_categories = {}
    for category in menu_order:
        if category in categories:
            # Plates already ordered by display_order from query
            plates_list = categories[category]
            ordered_categories[category] = plates_list

    # Add any remaining categories not in the predefined order
    for category, plates_list in categories.items():
        if category not in ordered_categories:
            ordered_categories[category] = plates_list

    # Get all available categories for the Add Plate modal
    all_categories = menu_order

    return render_template('plates.html',
                         categories=ordered_categories,
                         all_categories=all_categories)

@app.route('/plate/<path:plate_name>')
def plate_detail(plate_name):
    """Show detailed plate information with cost calculation."""
    try:
        import sqlite3

        # Get plate info including q_factor
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name, category, description, q_factor
                FROM plates
                WHERE name = ?
            """, (plate_name,))
            row = cursor.fetchone()

            if not row:
                flash(f"Plate '{plate_name}' not found", 'error')
                return redirect(url_for('plates'))

            plate = {
                'name': row[0],
                'category': row[1],
                'description': row[2],
                'q_factor': row[3] if row[3] is not None else 0.04
            }

        plate_ingredients = db_manager.get_plate_ingredients(plate_name)

        # Get recipes attached to this plate
        plate_recipes = []
        total_recipe_cost = 0.0
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT recipe_name, servings, quantity, unit
                FROM plate_recipes
                WHERE plate_name = ?
            """, (plate_name,))
            for row in cursor.fetchall():
                recipe_name, servings, quantity, unit = row
                # Get recipe details and calculate cost
                recipe_cost_data = db_manager.calculate_recipe_cost(recipe_name)
                if recipe_cost_data:
                    # Use quantity/unit if specified, otherwise fall back to servings
                    if quantity and unit:
                        # Calculate cost based on quantity
                        # If unit is 'servings', multiply cost_per_serving by quantity
                        # For other units, we'd need yield/conversion info (future enhancement)
                        if unit.lower() in ['servings', 'serving']:
                            recipe_total = recipe_cost_data['cost_per_serving'] * quantity
                        else:
                            # For non-serving units, use quantity as-is (may need conversion logic later)
                            recipe_total = recipe_cost_data['cost_per_serving'] * quantity
                        plate_recipes.append({
                            'name': recipe_name,
                            'quantity': quantity,
                            'unit': unit,
                            'servings': servings,
                            'cost_per_serving': recipe_cost_data['cost_per_serving'],
                            'total_cost': recipe_total
                        })
                    else:
                        recipe_total = recipe_cost_data['cost_per_serving'] * servings
                        plate_recipes.append({
                            'name': recipe_name,
                            'servings': servings,
                            'quantity': None,
                            'unit': None,
                            'cost_per_serving': recipe_cost_data['cost_per_serving'],
                            'total_cost': recipe_total
                        })
                    total_recipe_cost += recipe_total

        # Calculate direct ingredient costs
        ingredient_cost_data = db_manager.calculate_plate_cost(plate_name)
        direct_ingredient_cost = ingredient_cost_data['ingredient_cost'] if ingredient_cost_data else 0.0

        # NEW CALCULATION: Recipe costs + Direct ingredient costs, THEN apply Q-factor
        subtotal = total_recipe_cost + direct_ingredient_cost
        q_factor_cost = subtotal * plate['q_factor']
        total_cost = subtotal + q_factor_cost

        # Build corrected cost_data
        cost_data = {
            'recipe_cost': total_recipe_cost,
            'ingredient_cost': direct_ingredient_cost,
            'subtotal': subtotal,
            'q_factor': plate['q_factor'],
            'q_factor_cost': q_factor_cost,
            'total_cost': total_cost,
            'ingredient_breakdown': ingredient_cost_data['ingredient_breakdown'] if ingredient_cost_data else []
        }

        # Get allergens for the plate
        allergens = db_manager.get_plate_allergens(plate_name)
        allergen_details = []
        for allergen_code in sorted(allergens):
            info = db_manager.get_allergen_info(allergen_code)
            if info:
                allergen_details.append(info)

        return render_template('plate_detail.html',
                             plate=plate,
                             plate_ingredients=plate_ingredients,
                             plate_recipes=plate_recipes,
                             cost_data=cost_data,
                             allergens=allergen_details)

    except Exception as e:
        flash(f"Error loading plate: {str(e)}", 'error')
        return redirect(url_for('plates'))

@app.route('/plate/<path:plate_name>/add_ingredient', methods=['GET', 'POST'])
def add_ingredient_to_plate(plate_name):
    """Add ingredient to plate."""
    if request.method == 'POST':
        try:
            plate_ingredient = PlateIngredient(
                plate_name=plate_name,
                ingredient_name=request.form['ingredient_name'],
                quantity=float(request.form['quantity']),
                unit=request.form['unit']
            )

            if db_manager.add_plate_ingredient(plate_ingredient):
                flash(f"Ingredient added to {plate_name}", 'success')
            else:
                flash("Failed to add ingredient to plate", 'error')

        except ValueError:
            flash("Invalid quantity value", 'error')
        except Exception as e:
            flash(f"Error: {str(e)}", 'error')

        return redirect(url_for('plate_detail', plate_name=plate_name))

    # GET request - show form
    ingredients = db_manager.get_ingredients()
    recipes_raw = db_manager.get_recipes()

    # Group ingredients by category
    ingredients_by_category = {}
    for ing in ingredients:
        if ing.category not in ingredients_by_category:
            ingredients_by_category[ing.category] = []
        ingredients_by_category[ing.category].append(ing)

    # Get recipe cost data for each recipe
    recipes = []
    for recipe in recipes_raw:
        cost_data = db_manager.calculate_recipe_cost(recipe.name)
        recipes.append({
            'name': recipe.name,
            'servings': recipe.servings,
            'description': recipe.description,
            'total_cost': cost_data['total_cost'] if cost_data else 0.0
        })

    return render_template('add_ingredient_to_plate.html',
                         plate_name=plate_name,
                         ingredients_by_category=ingredients_by_category,
                         recipes=recipes)

@app.route('/plate/<path:plate_name>/add_recipe', methods=['POST'])
def add_recipe_to_plate(plate_name):
    """Add recipe to plate."""
    try:
        recipe_name = request.form['recipe_name']
        servings = float(request.form.get('servings', 1.0))
        quantity = request.form.get('quantity')
        unit = request.form.get('unit')

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # Convert quantity to float if provided
            if quantity:
                quantity = float(quantity)

            cursor.execute("""
                INSERT INTO plate_recipes (plate_name, recipe_name, servings, quantity, unit)
                VALUES (?, ?, ?, ?, ?)
            """, (plate_name, recipe_name, servings, quantity, unit))
            conn.commit()

        flash(f"Preparation '{recipe_name}' added to {plate_name}", 'success')

    except sqlite3.IntegrityError:
        flash(f"Preparation '{recipe_name}' is already in this plate", 'error')
    except ValueError:
        flash("Invalid quantity or servings value", 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')

    return redirect(url_for('plate_detail', plate_name=plate_name))

@app.route('/plate/<path:plate_name>/delete_ingredient/<path:ingredient_name>', methods=['POST'])
def delete_ingredient_from_plate(plate_name, ingredient_name):
    """Delete ingredient from plate."""
    try:
        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM plate_ingredients
                WHERE plate_name = ? AND ingredient_name = ?
            """, (plate_name, ingredient_name))
            conn.commit()

        flash(f"Ingredient '{ingredient_name}' removed from {plate_name}", 'success')

    except Exception as e:
        flash(f"Error: {str(e)}", 'error')

    return redirect(url_for('plate_detail', plate_name=plate_name))

@app.route('/plate/<path:plate_name>/delete_recipe/<path:recipe_name>', methods=['POST'])
def delete_recipe_from_plate(plate_name, recipe_name):
    """Delete recipe from plate."""
    try:
        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM plate_recipes
                WHERE plate_name = ? AND recipe_name = ?
            """, (plate_name, recipe_name))
            conn.commit()

        flash(f"Recipe '{recipe_name}' removed from {plate_name}", 'success')

    except Exception as e:
        flash(f"Error: {str(e)}", 'error')

    return redirect(url_for('plate_detail', plate_name=plate_name))

@app.route('/plate/<path:plate_name>/update_ingredient/<path:ingredient_name>', methods=['POST'])
def update_plate_ingredient(plate_name, ingredient_name):
    """Update ingredient quantity/unit in plate."""
    try:
        quantity = float(request.form['quantity'])
        unit = request.form['unit']

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE plate_ingredients
                SET quantity = ?, unit = ?
                WHERE plate_name = ? AND ingredient_name = ?
            """, (quantity, unit, plate_name, ingredient_name))
            conn.commit()

        flash(f"Ingredient '{ingredient_name}' updated", 'success')

    except ValueError:
        flash("Invalid quantity value", 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')

    return redirect(url_for('plate_detail', plate_name=plate_name))

@app.route('/plate/<path:plate_name>/update_recipe/<path:recipe_name>', methods=['POST'])
def update_plate_recipe(plate_name, recipe_name):
    """Update recipe quantity/unit/servings in plate."""
    try:
        quantity = request.form.get('quantity')
        unit = request.form.get('unit')
        servings = float(request.form.get('servings', 1.0))

        # Convert quantity to float if provided
        if quantity:
            quantity = float(quantity)

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE plate_recipes
                SET quantity = ?, unit = ?, servings = ?
                WHERE plate_name = ? AND recipe_name = ?
            """, (quantity, unit, servings, plate_name, recipe_name))
            conn.commit()

        flash(f"Preparation '{recipe_name}' updated", 'success')

    except ValueError:
        flash("Invalid quantity or servings value", 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')

    return redirect(url_for('plate_detail', plate_name=plate_name))

@app.route('/plate/<path:plate_name>/update_qfactor', methods=['POST'])
def update_plate_qfactor(plate_name):
    """Update Q-factor for a plate."""
    try:
        q_factor = float(request.form['q_factor'])

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE plates
                SET q_factor = ?
                WHERE name = ?
            """, (q_factor, plate_name))
            conn.commit()

        flash(f"Q-Factor updated to {q_factor * 100:.1f}%", 'success')

    except ValueError:
        flash("Invalid Q-Factor value", 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')

    return redirect(url_for('plate_detail', plate_name=plate_name))

@app.route('/recipe/<path:recipe_name>/update_prepfactor', methods=['POST'])
def update_recipe_prepfactor(recipe_name):
    """Update prep_factor for a recipe."""
    try:
        prep_factor = float(request.form['prep_factor'])

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE recipes
                SET prep_factor = ?
                WHERE name = ?
            """, (prep_factor, recipe_name))
            conn.commit()

        flash(f"Prep Factor updated to {prep_factor * 100:.1f}%", 'success')

    except ValueError:
        flash("Invalid Prep Factor value", 'error')
    except Exception as e:
        flash(f"Error: {str(e)}", 'error')

    return redirect(url_for('recipe_detail', recipe_name=recipe_name))

# =============================================================================
# PLATE CATEGORY MANAGEMENT
# =============================================================================

@app.route('/plate_categories')
def plate_categories():
    """Manage plate categories."""
    import sqlite3
    with sqlite3.connect(db_manager.db_path) as conn:
        cursor = conn.cursor()

        # Get categories with plate counts
        cursor.execute("""
            SELECT
                pc.id,
                pc.name,
                pc.display_order,
                COUNT(p.name) as plate_count
            FROM plate_categories pc
            LEFT JOIN plates p ON p.category = pc.name
            GROUP BY pc.id, pc.name, pc.display_order
            ORDER BY pc.display_order
        """)

        categories = []
        for row in cursor.fetchall():
            categories.append({
                'id': row[0],
                'name': row[1],
                'display_order': row[2],
                'plate_count': row[3]
            })

    return render_template('plate_categories.html', categories=categories)

@app.route('/plate_category/add', methods=['POST'])
def add_plate_category():
    """Add a new plate category."""
    try:
        category_name = request.form['category_name'].strip()

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # Get max display_order
            cursor.execute("SELECT MAX(display_order) FROM plate_categories")
            max_order = cursor.fetchone()[0] or 0

            cursor.execute("""
                INSERT INTO plate_categories (name, display_order)
                VALUES (?, ?)
            """, (category_name, max_order + 1))
            conn.commit()

        flash(f"Category '{category_name}' added successfully", 'success')

    except sqlite3.IntegrityError:
        flash(f"Category '{category_name}' already exists", 'error')
    except Exception as e:
        flash(f"Error adding category: {str(e)}", 'error')

    return redirect(url_for('plate_categories'))

@app.route('/plate_category/edit', methods=['POST'])
def edit_plate_category():
    """Rename a plate category."""
    try:
        category_id = int(request.form['category_id'])
        new_name = request.form['new_name'].strip()

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # Get old name
            cursor.execute("SELECT name FROM plate_categories WHERE id = ?", (category_id,))
            old_name = cursor.fetchone()[0]

            # Update category table
            cursor.execute("""
                UPDATE plate_categories
                SET name = ?
                WHERE id = ?
            """, (new_name, category_id))

            # Update all plates using this category
            cursor.execute("""
                UPDATE plates
                SET category = ?
                WHERE category = ?
            """, (new_name, old_name))

            conn.commit()

        flash(f"Category renamed from '{old_name}' to '{new_name}'", 'success')

    except sqlite3.IntegrityError:
        flash(f"Category '{new_name}' already exists", 'error')
    except Exception as e:
        flash(f"Error renaming category: {str(e)}", 'error')

    return redirect(url_for('plate_categories'))

@app.route('/plate_category/delete', methods=['POST'])
def delete_plate_category():
    """Delete a plate category (only if no plates use it)."""
    try:
        category_id = int(request.form['category_id'])

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # Get category name
            cursor.execute("SELECT name FROM plate_categories WHERE id = ?", (category_id,))
            category_name = cursor.fetchone()[0]

            # Check if any plates use this category
            cursor.execute("SELECT COUNT(*) FROM plates WHERE category = ?", (category_name,))
            plate_count = cursor.fetchone()[0]

            if plate_count > 0:
                flash(f"Cannot delete '{category_name}' - it has {plate_count} plate(s)", 'error')
            else:
                cursor.execute("DELETE FROM plate_categories WHERE id = ?", (category_id,))
                conn.commit()
                flash(f"Category '{category_name}' deleted successfully", 'success')

    except Exception as e:
        flash(f"Error deleting category: {str(e)}", 'error')

    return redirect(url_for('plate_categories'))

@app.route('/plate_category/move', methods=['POST'])
def move_plate_category():
    """Move a category up or down in display order."""
    try:
        category_id = int(request.form['category_id'])
        direction = request.form['direction']

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # Get current category
            cursor.execute("""
                SELECT id, display_order
                FROM plate_categories
                WHERE id = ?
            """, (category_id,))
            current = cursor.fetchone()
            current_order = current[1]

            if direction == 'up':
                # Swap with previous
                cursor.execute("""
                    SELECT id, display_order
                    FROM plate_categories
                    WHERE display_order < ?
                    ORDER BY display_order DESC
                    LIMIT 1
                """, (current_order,))
            else:  # down
                # Swap with next
                cursor.execute("""
                    SELECT id, display_order
                    FROM plate_categories
                    WHERE display_order > ?
                    ORDER BY display_order ASC
                    LIMIT 1
                """, (current_order,))

            swap_row = cursor.fetchone()
            if swap_row:
                swap_id, swap_order = swap_row

                # Swap orders
                cursor.execute("""
                    UPDATE plate_categories
                    SET display_order = ?
                    WHERE id = ?
                """, (swap_order, category_id))

                cursor.execute("""
                    UPDATE plate_categories
                    SET display_order = ?
                    WHERE id = ?
                """, (current_order, swap_id))

                conn.commit()
                flash("Category order updated", 'success')

    except Exception as e:
        flash(f"Error moving category: {str(e)}", 'error')

    return redirect(url_for('plate_categories'))

@app.route('/plate/add', methods=['POST'])
def add_plate():
    """Add a new plate."""
    try:
        plate_name = request.form['plate_name'].strip()
        category = request.form['category']
        description = request.form.get('description', '').strip()

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # Get max display_order for this category
            cursor.execute("""
                SELECT MAX(display_order) FROM plates WHERE category = ?
            """, (category,))
            max_order = cursor.fetchone()[0] or 0

            cursor.execute("""
                INSERT INTO plates (name, category, description, display_order, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (plate_name, category, description, max_order + 1))
            conn.commit()

        flash(f"Plate '{plate_name}' added successfully", 'success')

    except sqlite3.IntegrityError:
        flash(f"Plate '{plate_name}' already exists", 'error')
    except Exception as e:
        flash(f"Error adding plate: {str(e)}", 'error')

    return redirect(url_for('plates'))

@app.route('/plate/move', methods=['POST'])
def move_plate():
    """Move a plate up or down within its category."""
    try:
        plate_name = request.form['plate_name']
        category = request.form['category']
        direction = request.form['direction']

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()

            # Get current plate
            cursor.execute("""
                SELECT name, display_order
                FROM plates
                WHERE name = ? AND category = ?
            """, (plate_name, category))
            current = cursor.fetchone()
            current_order = current[1]

            if direction == 'up':
                # Swap with previous in same category
                cursor.execute("""
                    SELECT name, display_order
                    FROM plates
                    WHERE category = ? AND display_order < ? AND is_active = 1
                    ORDER BY display_order DESC
                    LIMIT 1
                """, (category, current_order))
            else:  # down
                # Swap with next in same category
                cursor.execute("""
                    SELECT name, display_order
                    FROM plates
                    WHERE category = ? AND display_order > ? AND is_active = 1
                    ORDER BY display_order ASC
                    LIMIT 1
                """, (category, current_order))

            swap_row = cursor.fetchone()
            if swap_row:
                swap_name, swap_order = swap_row

                # Swap orders
                cursor.execute("""
                    UPDATE plates
                    SET display_order = ?
                    WHERE name = ?
                """, (swap_order, plate_name))

                cursor.execute("""
                    UPDATE plates
                    SET display_order = ?
                    WHERE name = ?
                """, (current_order, swap_name))

                conn.commit()

    except Exception as e:
        flash(f"Error moving plate: {str(e)}", 'error')

    return redirect(url_for('plates'))

@app.route('/plate/archive', methods=['POST'])
def archive_plate():
    """Archive a plate (hide from menu but don't delete)."""
    try:
        plate_name = request.form['plate_name']

        import sqlite3
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE plates
                SET is_active = 0
                WHERE name = ?
            """, (plate_name,))
            conn.commit()

        flash(f"Plate '{plate_name}' archived successfully", 'success')

    except Exception as e:
        flash(f"Error archiving plate: {str(e)}", 'error')

    return redirect(url_for('plates'))

# =============================================================================
# API ENDPOINTS - RESTful JSON API for frontend integration
# =============================================================================

@app.route('/api', methods=['GET'])
@app.route('/api/', methods=['GET'])
def api_index():
    """API documentation and available endpoints."""
    endpoints = {
        'message': 'Recipe Management System API',
        'version': '1.0',
        'available_endpoints': {
            'statistics': {
                'GET /api/stats': 'Get dashboard statistics and inventory value'
            },
            'ingredients': {
                'GET /api/ingredients': 'List all ingredients',
                'GET /api/ingredients/<name>': 'Get specific ingredient details'
            },
            'recipes': {
                'GET /api/recipes': 'List all recipes with costs',
                'GET /api/recipes/<name>': 'Get specific recipe with details',
                'POST /api/recipes/<name>/scale': 'Scale recipe (requires JSON: {"scale_factor": 2.5})'
            },
            'plates': {
                'GET /api/plates': 'List all menu plates',
                'GET /api/plates/<name>': 'Get specific plate with costs'
            }
        },
        'sample_usage': {
            'get_stats': 'curl http://localhost:5000/api/stats',
            'scale_recipe': 'curl -X POST -H "Content-Type: application/json" -d \'{"scale_factor": 3}\' http://localhost:5000/api/recipes/Apple%20Pie/scale'
        }
    }

    return jsonify(endpoints)

@app.route('/api/ingredients', methods=['GET'])
def api_get_ingredients():
    """Get all ingredients as JSON."""
    try:
        ingredients = db_manager.get_ingredients()
        ingredients_data = []

        for ing in ingredients:
            ingredients_data.append({
                'name': ing.name,
                'category': ing.category,
                'purchase_unit': ing.purchase_unit,
                'purchase_price': float(ing.purchase_price),
                'inventory_unit': ing.inventory_unit,
                'units_per_purchase': float(ing.units_per_purchase),
                'cost_per_inventory_unit': float(ing.cost_per_inventory_unit),
                'recipe_unit': ing.recipe_unit,
                'recipe_units_per_inventory': float(ing.recipe_units_per_inventory),
                'cost_per_recipe_unit': float(ing.cost_per_recipe_unit),
                'yield_percent': float(ing.yield_percent),
                'on_hand': float(ing.on_hand) if ing.on_hand else 0,
                'supplier': ing.supplier,
                'notes': ing.notes
            })

        return jsonify({
            'success': True,
            'data': ingredients_data,
            'count': len(ingredients_data)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/ingredients/<path:ingredient_name>', methods=['GET'])
def api_get_ingredient(ingredient_name):
    """Get specific ingredient as JSON."""
    try:
        ingredients = db_manager.get_ingredients()
        ingredient = next((ing for ing in ingredients if ing.name == ingredient_name), None)

        if not ingredient:
            return jsonify({
                'success': False,
                'error': 'Ingredient not found'
            }), 404

        ingredient_data = {
            'name': ingredient.name,
            'category': ingredient.category,
            'purchase_unit': ingredient.purchase_unit,
            'purchase_price': float(ingredient.purchase_price),
            'inventory_unit': ingredient.inventory_unit,
            'units_per_purchase': float(ingredient.units_per_purchase),
            'cost_per_inventory_unit': float(ingredient.cost_per_inventory_unit),
            'recipe_unit': ingredient.recipe_unit,
            'recipe_units_per_inventory': float(ingredient.recipe_units_per_inventory),
            'cost_per_recipe_unit': float(ingredient.cost_per_recipe_unit),
            'yield_percent': float(ingredient.yield_percent),
            'on_hand': float(ingredient.on_hand) if ingredient.on_hand else 0,
            'supplier': ingredient.supplier,
            'notes': ingredient.notes
        }

        return jsonify({
            'success': True,
            'data': ingredient_data
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/recipes', methods=['GET'])
def api_get_recipes():
    """Get all recipes as JSON."""
    try:
        recipes = db_manager.get_recipes()
        recipes_data = []

        for recipe in recipes:
            # Get recipe ingredients
            recipe_ingredients = db_manager.get_recipe_ingredients(recipe.name)
            ingredients_list = []

            for ing in recipe_ingredients:
                ingredients_list.append({
                    'ingredient_name': ing.ingredient_name,
                    'quantity': float(ing.quantity),
                    'unit': ing.unit
                })

            # Calculate cost if possible
            try:
                cost_data = db_manager.calculate_recipe_cost(recipe.name)
                total_cost = cost_data.get('total_cost', 0) if cost_data else 0
                cost_per_serving = cost_data.get('cost_per_serving', 0) if cost_data else 0
            except:
                total_cost = 0
                cost_per_serving = 0

            recipes_data.append({
                'name': recipe.name,
                'servings': recipe.servings,
                'q_factor': float(recipe.q_factor),
                'category': getattr(recipe, 'category', 'Main'),
                'description': getattr(recipe, 'description', ''),
                'instructions': getattr(recipe, 'instructions', ''),
                'ingredients': ingredients_list,
                'total_cost': float(total_cost),
                'cost_per_serving': float(cost_per_serving)
            })

        return jsonify({
            'success': True,
            'data': recipes_data,
            'count': len(recipes_data)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/recipes/<path:recipe_name>', methods=['GET'])
def api_get_recipe(recipe_name):
    """Get specific recipe as JSON."""
    try:
        recipes = db_manager.get_recipes()
        recipe = next((r for r in recipes if r.name == recipe_name), None)

        if not recipe:
            return jsonify({
                'success': False,
                'error': 'Recipe not found'
            }), 404

        # Get recipe ingredients
        recipe_ingredients = db_manager.get_recipe_ingredients(recipe.name)
        ingredients_list = []

        for ing in recipe_ingredients:
            ingredients_list.append({
                'ingredient_name': ing.ingredient_name,
                'quantity': float(ing.quantity),
                'unit': ing.unit
            })

        # Calculate cost
        try:
            cost_data = db_manager.calculate_recipe_cost(recipe.name)
            total_cost = cost_data.get('total_cost', 0) if cost_data else 0
            cost_per_serving = cost_data.get('cost_per_serving', 0) if cost_data else 0
            ingredient_costs = cost_data.get('ingredient_costs', []) if cost_data else []
        except:
            total_cost = 0
            cost_per_serving = 0
            ingredient_costs = []

        recipe_data = {
            'name': recipe.name,
            'servings': recipe.servings,
            'q_factor': float(recipe.q_factor),
            'category': getattr(recipe, 'category', 'Main'),
            'description': getattr(recipe, 'description', ''),
            'instructions': getattr(recipe, 'instructions', ''),
            'ingredients': ingredients_list,
            'total_cost': float(total_cost),
            'cost_per_serving': float(cost_per_serving),
            'ingredient_costs': ingredient_costs
        }

        return jsonify({
            'success': True,
            'data': recipe_data
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/recipes/<path:recipe_name>/scale', methods=['POST'])
def api_scale_recipe(recipe_name):
    """Scale recipe and return JSON."""
    try:
        data = request.get_json()
        if not data or 'scale_factor' not in data:
            return jsonify({
                'success': False,
                'error': 'scale_factor required in JSON body'
            }), 400

        scale_factor = float(data['scale_factor'])
        if scale_factor <= 0:
            return jsonify({
                'success': False,
                'error': 'scale_factor must be positive'
            }), 400

        # Get original recipe
        recipes = db_manager.get_recipes()
        recipe = next((r for r in recipes if r.name == recipe_name), None)

        if not recipe:
            return jsonify({
                'success': False,
                'error': 'Recipe not found'
            }), 404

        # Get and scale ingredients
        recipe_ingredients = db_manager.get_recipe_ingredients(recipe.name)
        scaled_ingredients = []

        for ing in recipe_ingredients:
            scaled_quantity = float(ing.quantity) * scale_factor
            scaled_ingredients.append({
                'ingredient_name': ing.ingredient_name,
                'original_quantity': float(ing.quantity),
                'scaled_quantity': scaled_quantity,
                'unit': ing.unit
            })

        # Calculate scaled cost
        total_cost = 0
        for ing in scaled_ingredients:
            try:
                ingredients = db_manager.get_ingredients()
                ingredient = next((i for i in ingredients if i.name == ing['ingredient_name']), None)
                if ingredient:
                    # Calculate cost using cost_per_recipe_unit (already includes yield)
                    ingredient_cost = float(ingredient.cost_per_recipe_unit) * ing['scaled_quantity']
                    total_cost += ingredient_cost
                    ing['cost'] = ingredient_cost
            except:
                ing['cost'] = 0

        # Apply Q-factor
        q_factor_cost = total_cost * float(recipe.q_factor)
        final_cost = total_cost + q_factor_cost
        scaled_servings = recipe.servings * scale_factor
        cost_per_serving = final_cost / scaled_servings if scaled_servings > 0 else 0

        return jsonify({
            'success': True,
            'data': {
                'recipe_name': recipe_name,
                'scale_factor': scale_factor,
                'original_servings': recipe.servings,
                'scaled_servings': scaled_servings,
                'ingredients': scaled_ingredients,
                'total_ingredient_cost': total_cost,
                'q_factor_cost': q_factor_cost,
                'total_cost': final_cost,
                'cost_per_serving': cost_per_serving
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/plates', methods=['GET'])
def api_get_plates():
    """Get all plates as JSON."""
    try:
        plates = db_manager.get_plates()
        plates_data = []

        for plate in plates:
            # Get plate ingredients
            plate_ingredients = db_manager.get_plate_ingredients(plate.name)
            ingredients_list = []

            for ing in plate_ingredients:
                ingredients_list.append({
                    'ingredient_name': ing.ingredient_name,
                    'quantity': float(ing.quantity),
                    'unit': ing.unit
                })

            # Calculate cost if possible
            try:
                cost_data = db_manager.calculate_plate_cost(plate.name)
                total_cost = cost_data.get('total_cost', 0) if cost_data else 0
            except:
                total_cost = 0

            plates_data.append({
                'name': plate.name,
                'description': plate.description,
                'category': plate.category,
                'ingredients': ingredients_list,
                'total_cost': float(total_cost)
            })

        return jsonify({
            'success': True,
            'data': plates_data,
            'count': len(plates_data)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/plates/<path:plate_name>', methods=['GET'])
def api_get_plate(plate_name):
    """Get specific plate as JSON."""
    try:
        plates = db_manager.get_plates()
        plate = next((p for p in plates if p.name == plate_name), None)

        if not plate:
            return jsonify({
                'success': False,
                'error': 'Plate not found'
            }), 404

        # Get plate ingredients
        plate_ingredients = db_manager.get_plate_ingredients(plate.name)
        ingredients_list = []

        for ing in plate_ingredients:
            ingredients_list.append({
                'ingredient_name': ing.ingredient_name,
                'quantity': float(ing.quantity),
                'unit': ing.unit
            })

        # Calculate cost
        try:
            cost_data = db_manager.calculate_plate_cost(plate.name)
            total_cost = cost_data.get('total_cost', 0) if cost_data else 0
            ingredient_costs = cost_data.get('ingredient_costs', []) if cost_data else []
        except:
            total_cost = 0
            ingredient_costs = []

        plate_data = {
            'name': plate.name,
            'description': plate.description,
            'category': plate.category,
            'ingredients': ingredients_list,
            'total_cost': float(total_cost),
            'ingredient_costs': ingredient_costs
        }

        return jsonify({
            'success': True,
            'data': plate_data
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stats', methods=['GET'])
def api_get_stats():
    """Get dashboard statistics as JSON."""
    try:
        ingredients = db_manager.get_ingredients()
        recipes = db_manager.get_recipes()
        plates = db_manager.get_plates()

        stats = {
            'total_ingredients': len(ingredients),
            'total_recipes': len(recipes),
            'total_plates': len(plates),
            'categories': len(set(ing.category for ing in ingredients)),
            'avg_recipe_servings': round(sum(r.servings for r in recipes) / len(recipes), 1) if recipes else 0,
            'total_recipe_value': 0  # Could calculate total value of all recipes
        }

        # Calculate total inventory value
        total_inventory_value = 0
        for ing in ingredients:
            if hasattr(ing, 'on_hand') and ing.on_hand:
                total_inventory_value += float(ing.on_hand) * float(ing.cost_per_inventory_unit)

        stats['total_inventory_value'] = round(total_inventory_value, 2)

        return jsonify({
            'success': True,
            'data': stats
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/prep-list')
def prep_list():
    """Prep list page showing what needs to be prepped by station."""
    import sqlite3

    with sqlite3.connect(str(DB_PATH)) as conn:
        cursor = conn.cursor()

        # Get all recipes with prep tracking
        cursor.execute("""
            SELECT name, station, prepared_servings, par_servings,
                   (par_servings - prepared_servings) as need
            FROM recipes
            WHERE station != 'Beverage'
            ORDER BY station, name
        """)

        recipes_data = cursor.fetchall()

        # Group by station
        stations = {}
        for name, station, prepared, par, need in recipes_data:
            if station not in stations:
                stations[station] = {
                    'station': station,
                    'items': [],
                    'total_below_par': 0
                }

            status = 'ok' if prepared >= par else 'low' if prepared >= par * 0.5 else 'critical'

            stations[station]['items'].append({
                'name': name,
                'prepared': prepared,
                'par': par,
                'need': max(0, need),
                'status': status
            })

            if need > 0:
                stations[station]['total_below_par'] += 1

        # Convert to list and sort
        stations_list = sorted(stations.values(), key=lambda x: x['station'])

    return render_template('prep_list.html', stations=stations_list)

@app.route('/api/recipe/<path:recipe_name>/update_prepared', methods=['POST'])
def update_prepared_servings(recipe_name):
    """API endpoint to update prepared_servings for a recipe."""
    import sqlite3

    data = request.get_json()
    new_value = data.get('prepared_servings')

    if new_value is None or new_value < 0:
        return jsonify({'error': 'Invalid prepared_servings value'}), 400

    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE recipes SET prepared_servings = ? WHERE name = ?",
                (new_value, recipe_name)
            )
            conn.commit()

            # Return updated values
            cursor.execute(
                "SELECT prepared_servings, par_servings FROM recipes WHERE name = ?",
                (recipe_name,)
            )
            row = cursor.fetchone()
            if row:
                prepared, par = row
                return jsonify({
                    'success': True,
                    'prepared_servings': prepared,
                    'par_servings': par,
                    'need': max(0, par - prepared)
                })
            else:
                return jsonify({'error': 'Recipe not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/bulk-inventory')
def bulk_inventory():
    """Bulk inventory status showing items below par."""
    import sqlite3

    with sqlite3.connect(str(DB_PATH)) as conn:
        cursor = conn.cursor()

        # Get all ingredients with inventory tracking and check if used in recipes OR plates
        cursor.execute("""
            SELECT i.id, i.name, i.category, i.on_hand, i.par_level, i.inventory_unit,
                   (i.par_level - i.on_hand) as need,
                   CASE WHEN (ri.ingredient_name IS NOT NULL OR pi.ingredient_name IS NOT NULL)
                        THEN 1 ELSE 0 END as is_used
            FROM ingredients i
            LEFT JOIN recipe_ingredients ri ON i.name = ri.ingredient_name
            LEFT JOIN plate_ingredients pi ON i.name = pi.ingredient_name
            GROUP BY i.id, i.name, i.category, i.on_hand, i.par_level, i.inventory_unit
            ORDER BY i.category, i.name
        """)

        ingredients_data = cursor.fetchall()

        # Group by category
        categories = {}
        below_par_count = 0

        for id, name, category, on_hand, par, inventory_unit, need, is_used in ingredients_data:
            if category not in categories:
                categories[category] = {
                    'category': category,
                    'items': [],
                    'below_par': 0
                }

            status = 'ok' if on_hand >= par else 'low' if on_hand >= par * 0.5 else 'critical'

            categories[category]['items'].append({
                'id': id,
                'name': name,
                'on_hand': on_hand,
                'par': par,
                'inventory_unit': inventory_unit,
                'need': max(0, need),
                'status': status,
                'is_used': is_used
            })

            if need > 0:
                categories[category]['below_par'] += 1
                below_par_count += 1

        # Convert to list and sort
        categories_list = sorted(categories.values(), key=lambda x: x['category'])

    return render_template('bulk_inventory.html', categories=categories_list, below_par_count=below_par_count)

@app.route('/api/ingredient/<path:ingredient_name>/update_onhand', methods=['POST'])
def update_ingredient_onhand(ingredient_name):
    """API endpoint to update on_hand for an ingredient."""
    import sqlite3

    data = request.get_json()
    new_value = data.get('on_hand')

    if new_value is None or new_value < 0:
        return jsonify({'error': 'Invalid on_hand value'}), 400

    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE ingredients SET on_hand = ? WHERE name = ?",
                (new_value, ingredient_name)
            )
            conn.commit()

            # Return updated values
            cursor.execute(
                "SELECT on_hand, par_level, recipe_unit FROM ingredients WHERE name = ?",
                (ingredient_name,)
            )
            row = cursor.fetchone()
            if row:
                on_hand, par, recipe_unit = row
                return jsonify({
                    'success': True,
                    'on_hand': on_hand,
                    'par_level': par,
                    'need': max(0, par - on_hand),
                    'recipe_unit': recipe_unit
                })
            else:
                return jsonify({'error': 'Ingredient not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    if not DB_PATH.exists():
        print("❌ Database not found. Please run the migration script first:")
        print("   python3 fix_and_import_data.py")
        exit(1)

    print("🍳 Starting Recipe Management System Web Interface...")
    print("📂 Database:", DB_PATH)
    print("🌐 Open your browser to: http://localhost:5000")
    print("🛑 Press Ctrl+C to stop the server")

    app.run(debug=True, host='0.0.0.0', port=5000)