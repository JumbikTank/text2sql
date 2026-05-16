-- Create metadata table for vector search
USE ecommerce;

-- Notes table for storing table metadata with embeddings
CREATE TABLE notes (
    id INT PRIMARY KEY AUTO_INCREMENT,
    table_name VARCHAR(255) NOT NULL,
    table_comments TEXT,
    full_description TEXT,
    description TEXT,
    embedding VECTOR(384) COMMENT 'hnsw(distance=cosine)'
) COMMENT='Metadata table for vector search of database tables';

-- Insert metadata for each table
INSERT INTO notes (table_name, table_comments, full_description, description) VALUES
(
    'customers',
    'Customer information including contact details and purchase history',
    'The customers table stores all customer data including personal information (first_name, last_name, email, phone), location data (city, country), registration details (registration_date), and spending metrics (total_spent). This table is essential for customer relationship management, sales analysis, and demographic reporting.',
    'Columns: customer_id (INT, PRIMARY KEY), first_name (VARCHAR 50), last_name (VARCHAR 50), email (VARCHAR 100, UNIQUE), phone (VARCHAR 20), city (VARCHAR 50), country (VARCHAR 50), registration_date (DATE), total_spent (DECIMAL 10,2)'
),
(
    'products',
    'Product catalog with pricing and inventory information',
    'The products table contains the complete product catalog including product details (product_name, description), categorization (category), pricing information (price), inventory levels (stock_quantity), supplier information (supplier), and customer ratings (rating). This table is crucial for inventory management, pricing strategies, and product performance analysis.',
    'Columns: product_id (INT, PRIMARY KEY), product_name (VARCHAR 100), category (VARCHAR 50), price (DECIMAL 10,2), stock_quantity (INT), supplier (VARCHAR 100), rating (DECIMAL 3,2), description (TEXT)'
),
(
    'orders',
    'Customer orders with status and payment information',
    'The orders table tracks all customer orders with order details (order_id, order_date), customer linkage (customer_id as FOREIGN KEY to customers table), order status tracking (status: pending/processing/shipped/delivered), financial information (total_amount), delivery details (shipping_address), and payment methods (payment_method). This table is essential for order management, sales reporting, and customer service.',
    'Columns: order_id (INT, PRIMARY KEY), customer_id (INT, FOREIGN KEY to customers), order_date (DATETIME), status (VARCHAR 20), total_amount (DECIMAL 10,2), shipping_address (TEXT), payment_method (VARCHAR 50)'
),
(
    'order_items',
    'Individual line items for each order',
    'The order_items table stores the detailed line items for each order, linking orders to products. It contains item identification (item_id), order linkage (order_id as FOREIGN KEY to orders table), product linkage (product_id as FOREIGN KEY to products table), quantity information (quantity), pricing at time of purchase (unit_price), and calculated totals (subtotal). This table is crucial for detailed sales analysis, product performance tracking, and order fulfillment.',
    'Columns: item_id (INT, PRIMARY KEY), order_id (INT, FOREIGN KEY to orders), product_id (INT, FOREIGN KEY to products), quantity (INT), unit_price (DECIMAL 10,2), subtotal (DECIMAL 10,2)'
);

-- Generate embeddings using MySQL HeatWave ML_EMBED
UPDATE notes
SET embedding = ML_EMBED_ROW(
    CONCAT(table_name, ' ', table_comments, ' ', full_description, ' ', description),
    JSON_OBJECT('model_id', 'multilingual-e5-small')
);
