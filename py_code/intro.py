from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import mysql.connector
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import os
from sklearn.linear_model import LinearRegression

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Database connection
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="1234",
        database="truck"
    )

# Home / Login page
@app.route('/')
def home():
    session.clear()
    return render_template('Login.html')

# Login confirmation
@app.route("/Confirm", methods=['POST', 'GET'])
def base():
    name = request.form.get('Uname')
    key = request.form.get('pass')
    if key == 'ultron':
        session['logged_in'] = True
        session['role'] = 'admin' if name.lower() == 'admin' else 'user'
        return redirect(url_for('dashboard' if session['role'] == 'admin' else 'purchase'))
    else:
        return render_template('Login.html', error="Invalid username or password!")

# Truck purchase listing
@app.route('/purchase')
def purchase():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM truckmodels ORDER BY truck_name, truck_model")
    trucks = cursor.fetchall()
    conn.close()
    return render_template('purchase.html', trucks=trucks)

# Truck comparison (admin only) with dynamic dropdowns
@app.route('/Compare')
def compare():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('home'))
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT truck_name FROM truckmodels ORDER BY truck_name")
    brands = [row['truck_name'] for row in cursor.fetchall()]
    brand_model_map = {}
    for brand in brands:
        cursor.execute("SELECT truck_model FROM truckmodels WHERE truck_name = %s ORDER BY truck_model", (brand,))
        brand_model_map[brand] = [r['truck_model'] for r in cursor.fetchall()]
    conn.close()
    return render_template('compare.html', brands=brands, brand_model_map=brand_model_map)

# API for returning truck specs in comparison modal (AJAX endpoint)
@app.route('/get_truck_specs', methods=['POST'])
def get_truck_specs():
    data = request.get_json()
    brand = data.get('brand')
    model = data.get('model')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM truckmodels WHERE truck_name=%s AND truck_model=%s", (brand, model))
    truck = cursor.fetchone()
    conn.close()
    return jsonify(truck or {})

# Dashboard (admin only)
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('home'))
    return render_template('Base.html')

# Customer order entry page
@app.route('/purchase/<int:truck_id>')
def customer_details(truck_id):
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    return render_template('customer_details.html', truck_id=truck_id)

# Handle purchase form submit
@app.route('/submit_purchase', methods=['POST'])
def submit_purchase():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    truck_id = int(request.form.get('truck_id'))
    name = request.form.get('name')
    phone = request.form.get('phone')
    email = request.form.get('email')
    city = request.form.get('address')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT MAX(order_id) FROM orders")
    result = cursor.fetchone()
    new_id = (result['MAX(order_id)'] or 0) + 1
    cursor.execute("""
        INSERT INTO orders (order_id, truck_id, customer_name, customer_city, contact_no, purchase_date, email)
        VALUES (%s, %s, %s, %s, %s, CURDATE(), %s)
    """, (new_id, truck_id, name, city, phone, email))
    conn.commit()
    cursor.execute("""
        SELECT truck_name, truck_model, truck_type, load_capacity, price, image_url, engine_power, fuel_type, num_of_axles, mileage, seating_capacity
        FROM truckmodels WHERE truck_id = %s
    """, (truck_id,))
    truck = cursor.fetchone()
    conn.close()
    session.clear()
    return render_template('confirmation.html', name=name, truck=truck)

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# Login page shortcut
@app.route('/login')
def login():
    return render_template('Login.html')

# Truck sales analytics (admin only)
@app.route('/sales', methods=['GET', 'POST'])
def sales():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('home'))
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT truck_name FROM truckmodels ORDER BY truck_name")
    brands = [row['truck_name'] for row in cursor.fetchall()]
    selected_brand = request.form.get('truck_brand')
    selected_model = request.form.get('truck_model')
    models = []
    if selected_brand:
        cursor.execute("SELECT DISTINCT truck_model FROM truckmodels WHERE truck_name = %s ORDER BY truck_model",
                       (selected_brand,))
        models = [row['truck_model'] for row in cursor.fetchall()]
    if request.method == 'POST' and selected_brand and selected_model:
        query = """
            SELECT o.purchase_date AS sale_date, t.price
            FROM orders o
            JOIN truckmodels t ON o.truck_id = t.truck_id
            WHERE t.truck_name = %s AND t.truck_model = %s
        """
        df = pd.read_sql(query, conn, params=(selected_brand, selected_model))
        if df.empty:
            conn.close()
            return render_template("graph.html", no_data=True, truck_model=f"{selected_brand} - {selected_model}")
        df['month'] = pd.to_datetime(df['sale_date']).dt.to_period('M').astype(str)
        monthly_sales = df.groupby('month')['price'].sum().reset_index()
        monthly_sales['month_index'] = range(len(monthly_sales))
        model = LinearRegression()
        model.fit(monthly_sales[['month_index']], monthly_sales['price'])
        future_indexes = [[i] for i in range(len(monthly_sales), len(monthly_sales) + 3)]
        predictions = model.predict(future_indexes)
        future_months = pd.date_range(
            start=pd.to_datetime(monthly_sales['month'].iloc[-1]) + pd.offsets.MonthBegin(),
            periods=3,
            freq='MS'
        ).strftime('%Y-%m')
        plt.figure(figsize=(10, 5))
        ax = plt.gca()
        ax.plot(monthly_sales['month'], monthly_sales['price'], label='Actual Sales', marker='o')
        ax.plot(future_months, predictions, label='Predicted Sales', linestyle='--', marker='x')
        ax.set_xlabel('Month')
        ax.set_ylabel('Total Sales')
        ax.set_title(f"Truck Sales Forecast for {selected_brand} - {selected_model}")
        ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax.legend(loc='upper right')
        plt.xticks(rotation=45)
        plt.tight_layout()
        graph_path = os.path.join('static', 'truck_graph.png')
        plt.savefig(graph_path)
        plt.close()
        city_query = """
            SELECT o.customer_city, COUNT(*) AS total_sales
            FROM orders o
            JOIN truckmodels t ON o.truck_id = t.truck_id
            WHERE t.truck_name = %s AND t.truck_model = %s
            GROUP BY o.customer_city
        """
        city_df = pd.read_sql(city_query, conn, params=(selected_brand, selected_model))
        plt.figure(figsize=(10, 5))
        plt.bar(city_df['customer_city'], city_df['total_sales'], color='teal')
        plt.xlabel('City')
        plt.ylabel('Total Sales')
        plt.title(f"Sales by City for {selected_brand} - {selected_model}")
        plt.xticks(rotation=45)
        plt.tight_layout()
        bar_path = os.path.join('static', 'truck_bargraph.png')
        plt.savefig(bar_path)
        plt.close()
        conn.close()
        return render_template('graph.html',
                               graph_url=graph_path,
                               bar_url=bar_path,
                               truck_model=f"{selected_brand} - {selected_model}")
    conn.close()
    return render_template('sales.html', brands=brands, models=models, selected_brand=selected_brand)

if __name__ == '__main__':
    app.run(debug=True)
