-- Create the (empty) database once. Tables are created/upgraded automatically and non-destructively by the
-- backend at startup (app/database/migrate.py). Do NOT drop an existing database to upgrade.
CREATE DATABASE IF NOT EXISTS synthetic_user_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
