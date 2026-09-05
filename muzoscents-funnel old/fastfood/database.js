// database.js
const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const dbPath = path.join(__dirname, 'hotportion.db');
const db = new sqlite3.Database(dbPath);

// Initialize tables
db.serialize(() => {
  // Categories
  db.run(`
    CREATE TABLE IF NOT EXISTS categories (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL
    )
  `);

  // Products
  db.run(`
    CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      description TEXT,
      price REAL NOT NULL,
      stock INTEGER DEFAULT 0,
      tag TEXT NOT NULL,           -- category name (denormalized for simplicity)
      emoji TEXT,
      image TEXT,
      tagColor TEXT DEFAULT 'primary'
    )
  `);

  // Orders
  db.run(`
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      paymentReference TEXT UNIQUE NOT NULL,
      customerName TEXT NOT NULL,
      customerPhone TEXT NOT NULL,
      total REAL NOT NULL,
      status TEXT DEFAULT 'pending',
      deliveryMethod TEXT,
      deliveryAddress TEXT,
      preferredTime TEXT,
      orderNotes TEXT,
      createdAt DATETIME DEFAULT CURRENT_TIMESTAMP
    )
  `);

  // Order items
  db.run(`
    CREATE TABLE IF NOT EXISTS order_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      orderId INTEGER NOT NULL,
      productName TEXT NOT NULL,
      qty INTEGER NOT NULL,
      price REAL NOT NULL,
      FOREIGN KEY (orderId) REFERENCES orders(id) ON DELETE CASCADE
    )
  `);

  // Insert default categories if empty
  db.get(`SELECT COUNT(*) as count FROM categories`, (err, row) => {
    if (err) return;
    if (row.count === 0) {
      const defaultCategories = [
        'Burgers', 'Rice Dishes', 'Swallow & Soups', 'Specialties',
        'Grilled & Roast', 'Beans, Yam & Plantain', 'Snacks', 'Beverages'
      ];
      const stmt = db.prepare(`INSERT INTO categories (name) VALUES (?)`);
      defaultCategories.forEach(name => stmt.run(name));
      stmt.finalize();
    }
  });
});

module.exports = db;
