-- E-commerce Sample Database Schema

USE ecommerce;

-- Customers table
CREATE TABLE customers (
    customer_id INT PRIMARY KEY AUTO_INCREMENT,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20),
    city VARCHAR(50),
    country VARCHAR(50),
    registration_date DATE,
    total_spent DECIMAL(10, 2) DEFAULT 0.00
) COMMENT='Customer information including contact details and purchase history';

-- Products table
CREATE TABLE products (
    product_id INT PRIMARY KEY AUTO_INCREMENT,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    price DECIMAL(10, 2) NOT NULL,
    stock_quantity INT DEFAULT 0,
    supplier VARCHAR(100),
    rating DECIMAL(3, 2),
    description TEXT
) COMMENT='Product catalog with pricing and inventory information';

-- Orders table
CREATE TABLE orders (
    order_id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT NOT NULL,
    order_date DATETIME NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    total_amount DECIMAL(10, 2) NOT NULL,
    shipping_address TEXT,
    payment_method VARCHAR(50),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
) COMMENT='Customer orders with status and payment information';

-- Order Items table
CREATE TABLE order_items (
    item_id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,
    subtotal DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
) COMMENT='Individual line items for each order';

-- Insert sample customers
INSERT INTO customers (first_name, last_name, email, phone, city, country, registration_date, total_spent) VALUES
('John', 'Smith', 'john.smith@email.com', '+1-555-0101', 'New York', 'USA', '2024-01-15', 2500.00),
('Maria', 'Garcia', 'maria.garcia@email.com', '+1-555-0102', 'Los Angeles', 'USA', '2024-02-20', 1800.50),
('李', '明', 'li.ming@email.com', '+86-138-0000-0001', 'Beijing', 'China', '2024-03-10', 3200.00),
('Anna', 'Müller', 'anna.mueller@email.de', '+49-30-12345678', 'Berlin', 'Germany', '2024-01-25', 1500.75),
('Иван', 'Петров', 'ivan.petrov@email.ru', '+7-495-1234567', 'Moscow', 'Russia', '2024-04-05', 950.00),
('Sophie', 'Dubois', 'sophie.dubois@email.fr', '+33-1-23456789', 'Paris', 'France', '2024-02-14', 2100.00),
('Ahmed', 'Hassan', 'ahmed.hassan@email.com', '+20-2-12345678', 'Cairo', 'Egypt', '2024-03-20', 800.00),
('Yuki', 'Tanaka', 'yuki.tanaka@email.jp', '+81-3-12345678', 'Tokyo', 'Japan', '2024-01-30', 2800.00);

-- Insert sample products
INSERT INTO products (product_name, category, price, stock_quantity, supplier, rating, description) VALUES
('Laptop Pro 15"', 'Electronics', 1299.99, 45, 'TechSupply Inc', 4.5, 'High-performance laptop with 16GB RAM and 512GB SSD'),
('Wireless Mouse', 'Electronics', 29.99, 150, 'TechSupply Inc', 4.2, 'Ergonomic wireless mouse with precision tracking'),
('Office Chair Deluxe', 'Furniture', 249.99, 30, 'Furniture World', 4.7, 'Ergonomic office chair with lumbar support'),
('Coffee Maker Premium', 'Appliances', 89.99, 60, 'HomeGoods Ltd', 4.3, 'Programmable coffee maker with thermal carafe'),
('Running Shoes Pro', 'Sportswear', 129.99, 80, 'SportGear Co', 4.6, 'Professional running shoes with advanced cushioning'),
('Backpack Travel 40L', 'Accessories', 79.99, 100, 'TravelPro', 4.4, 'Durable travel backpack with laptop compartment'),
('Smartphone X12', 'Electronics', 899.99, 25, 'TechSupply Inc', 4.8, '5G smartphone with triple camera system'),
('Desk Lamp LED', 'Furniture', 45.99, 120, 'Furniture World', 4.1, 'Adjustable LED desk lamp with touch controls'),
('Water Bottle Insulated', 'Accessories', 24.99, 200, 'SportGear Co', 4.5, '32oz insulated water bottle keeps drinks cold 24hrs'),
('Yoga Mat Premium', 'Sportswear', 39.99, 90, 'SportGear Co', 4.6, 'Non-slip yoga mat with carrying strap');

-- Insert sample orders
INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, payment_method) VALUES
(1, '2024-11-01 10:30:00', 'delivered', 1329.98, '123 Main St, New York, NY 10001', 'credit_card'),
(2, '2024-11-05 14:15:00', 'delivered', 169.97, '456 Oak Ave, Los Angeles, CA 90001', 'paypal'),
(3, '2024-11-10 09:20:00', 'shipped', 1079.97, 'Building 5, Chaoyang District, Beijing 100000', 'credit_card'),
(1, '2024-11-15 16:45:00', 'processing', 299.98, '123 Main St, New York, NY 10001', 'credit_card'),
(4, '2024-11-18 11:00:00', 'delivered', 384.96, 'Hauptstraße 10, 10115 Berlin', 'bank_transfer'),
(5, '2024-11-20 13:30:00', 'delivered', 949.98, 'Tverskaya St, Moscow 125009', 'credit_card'),
(6, '2024-11-22 15:20:00', 'shipped', 329.97, '10 Rue de Rivoli, 75001 Paris', 'paypal'),
(7, '2024-11-25 10:10:00', 'pending', 119.98, '5 Tahrir Square, Cairo 11511', 'cash_on_delivery'),
(8, '2024-11-27 12:00:00', 'processing', 1829.97, '1-1-1 Shibuya, Tokyo 150-0002', 'credit_card');

-- Insert order items
INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal) VALUES
-- Order 1
(1, 1, 1, 1299.99, 1299.99),
(1, 2, 1, 29.99, 29.99),
-- Order 2
(2, 5, 1, 129.99, 129.99),
(2, 9, 1, 24.99, 24.99),
(2, 10, 1, 39.99, 39.99),
-- Order 3
(3, 7, 1, 899.99, 899.99),
(3, 2, 2, 29.99, 59.98),
(3, 6, 1, 79.99, 79.99),
(3, 9, 2, 24.99, 49.98),
-- Order 4
(4, 3, 1, 249.99, 249.99),
(4, 8, 1, 45.99, 45.99),
-- Order 5
(5, 4, 2, 89.99, 179.98),
(5, 8, 3, 45.99, 137.97),
(5, 9, 3, 24.99, 74.97),
-- Order 6
(6, 1, 1, 1299.99, 1299.99),
-- Order 7
(7, 6, 1, 79.99, 79.99),
(7, 5, 1, 129.99, 129.99),
(7, 10, 1, 39.99, 39.99),
-- Order 8
(8, 9, 4, 24.99, 99.96),
(8, 10, 1, 39.99, 39.99),
-- Order 9
(9, 7, 2, 899.99, 1799.98),
(9, 2, 1, 29.99, 29.99);
