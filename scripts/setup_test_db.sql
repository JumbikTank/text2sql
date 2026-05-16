-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create sample e-commerce schema

-- Customers table
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE customers IS 'Customer information including contact details and registration date';
COMMENT ON COLUMN customers.email IS 'Unique email address used for login and communication';
COMMENT ON COLUMN customers.phone IS 'Optional phone number for order notifications';

-- Product categories
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    parent_id INTEGER REFERENCES categories(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE categories IS 'Product categories with hierarchical structure support';

-- Products table
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    cost DECIMAL(10, 2),
    stock_quantity INTEGER NOT NULL DEFAULT 0,
    category_id INTEGER REFERENCES categories(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE products IS 'Product catalog with pricing, inventory, and categorization';
COMMENT ON COLUMN products.sku IS 'Stock Keeping Unit - unique product identifier';
COMMENT ON COLUMN products.price IS 'Current selling price in USD';
COMMENT ON COLUMN products.cost IS 'Product cost for margin calculation';

-- Orders table
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(20) NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    subtotal DECIMAL(10, 2) NOT NULL,
    tax DECIMAL(10, 2) NOT NULL DEFAULT 0,
    shipping DECIMAL(10, 2) NOT NULL DEFAULT 0,
    total DECIMAL(10, 2) NOT NULL,
    shipping_address TEXT,
    billing_address TEXT,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_status CHECK (status IN ('pending', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled'))
);

COMMENT ON TABLE orders IS 'Customer orders with status tracking and address information';
COMMENT ON COLUMN orders.status IS 'Order lifecycle status: pending, confirmed, processing, shipped, delivered, cancelled';

-- Order items table
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,
    total_price DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE order_items IS 'Individual line items within an order';

-- Inventory movements
CREATE TABLE inventory_movements (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    movement_type VARCHAR(20) NOT NULL,
    quantity INTEGER NOT NULL,
    reference_id INTEGER,
    reference_type VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_movement_type CHECK (movement_type IN ('purchase', 'sale', 'adjustment', 'return'))
);

COMMENT ON TABLE inventory_movements IS 'Stock movement history for inventory tracking and auditing';

-- Create indexes
CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_inventory_product ON inventory_movements(product_id);

-- Insert sample data

-- Categories
INSERT INTO categories (name, description) VALUES
    ('Electronics', 'Electronic devices and accessories'),
    ('Clothing', 'Apparel and fashion items'),
    ('Home & Garden', 'Home improvement and garden supplies');

INSERT INTO categories (name, description, parent_id) VALUES
    ('Smartphones', 'Mobile phones and accessories', 1),
    ('Laptops', 'Portable computers', 1),
    ('Men''s Clothing', 'Men''s apparel', 2),
    ('Women''s Clothing', 'Women''s apparel', 2);

-- Customers
INSERT INTO customers (email, first_name, last_name, phone) VALUES
    ('john.doe@example.com', 'John', 'Doe', '+1-555-0101'),
    ('jane.smith@example.com', 'Jane', 'Smith', '+1-555-0102'),
    ('bob.wilson@example.com', 'Bob', 'Wilson', NULL),
    ('alice.johnson@example.com', 'Alice', 'Johnson', '+1-555-0104'),
    ('charlie.brown@example.com', 'Charlie', 'Brown', '+1-555-0105');

-- Products
INSERT INTO products (sku, name, description, price, cost, stock_quantity, category_id) VALUES
    ('PHONE-001', 'Smartphone Pro X', 'Latest flagship smartphone with 5G', 999.99, 650.00, 50, 4),
    ('PHONE-002', 'Smartphone Lite', 'Budget-friendly smartphone', 299.99, 180.00, 100, 4),
    ('LAPTOP-001', 'ProBook 15', 'Professional laptop with 16GB RAM', 1299.99, 850.00, 25, 5),
    ('LAPTOP-002', 'UltraBook Air', 'Lightweight laptop for travel', 999.99, 620.00, 30, 5),
    ('SHIRT-001', 'Classic Oxford Shirt', 'Men''s button-down shirt', 59.99, 25.00, 200, 6),
    ('DRESS-001', 'Summer Floral Dress', 'Women''s casual dress', 79.99, 35.00, 150, 7),
    ('JEANS-001', 'Slim Fit Jeans', 'Men''s denim jeans', 89.99, 40.00, 180, 6);

-- Orders
INSERT INTO orders (order_number, customer_id, status, subtotal, tax, shipping, total, shipping_address) VALUES
    ('ORD-2024-0001', 1, 'delivered', 1099.98, 88.00, 0.00, 1187.98, '123 Main St, New York, NY 10001'),
    ('ORD-2024-0002', 2, 'shipped', 299.99, 24.00, 9.99, 333.98, '456 Oak Ave, Los Angeles, CA 90001'),
    ('ORD-2024-0003', 1, 'processing', 1359.98, 108.80, 0.00, 1468.78, '123 Main St, New York, NY 10001'),
    ('ORD-2024-0004', 3, 'pending', 149.97, 12.00, 5.99, 167.96, '789 Pine Rd, Chicago, IL 60601'),
    ('ORD-2024-0005', 4, 'cancelled', 999.99, 80.00, 0.00, 1079.99, '321 Elm St, Houston, TX 77001');

-- Order items
INSERT INTO order_items (order_id, product_id, quantity, unit_price, total_price) VALUES
    (1, 1, 1, 999.99, 999.99),
    (1, 5, 1, 59.99, 59.99),
    (1, 7, 1, 40.00, 40.00),
    (2, 2, 1, 299.99, 299.99),
    (3, 3, 1, 1299.99, 1299.99),
    (3, 5, 1, 59.99, 59.99),
    (4, 5, 1, 59.99, 59.99),
    (4, 7, 1, 89.98, 89.98),
    (5, 1, 1, 999.99, 999.99);

-- Inventory movements
INSERT INTO inventory_movements (product_id, movement_type, quantity, reference_type, notes) VALUES
    (1, 'purchase', 100, 'purchase_order', 'Initial stock'),
    (1, 'sale', -2, 'order', 'Order ORD-2024-0001, ORD-2024-0005'),
    (2, 'purchase', 150, 'purchase_order', 'Initial stock'),
    (2, 'sale', -1, 'order', 'Order ORD-2024-0002'),
    (3, 'purchase', 50, 'purchase_order', 'Initial stock'),
    (3, 'sale', -1, 'order', 'Order ORD-2024-0003'),
    (5, 'purchase', 250, 'purchase_order', 'Initial stock'),
    (5, 'sale', -3, 'order', 'Multiple orders'),
    (7, 'purchase', 200, 'purchase_order', 'Initial stock'),
    (7, 'adjustment', -20, 'adjustment', 'Damaged inventory write-off');

-- Create a view for order summaries
CREATE VIEW order_summary AS
SELECT
    o.id,
    o.order_number,
    c.email as customer_email,
    c.first_name || ' ' || c.last_name as customer_name,
    o.status,
    o.total,
    COUNT(oi.id) as item_count,
    o.created_at
FROM orders o
JOIN customers c ON o.customer_id = c.id
LEFT JOIN order_items oi ON o.id = oi.order_id
GROUP BY o.id, o.order_number, c.email, c.first_name, c.last_name, o.status, o.total, o.created_at;

COMMENT ON VIEW order_summary IS 'Aggregated order view with customer info and item counts';

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO testuser;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO testuser;
