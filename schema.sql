CREATE DATABASE IF NOT EXISTS mealmind CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE mealmind;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100),
  email VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (name,email) VALUES ('Default User','user@example.com') ON DUPLICATE KEY UPDATE email=email;

CREATE TABLE IF NOT EXISTS dishes (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  cuisine VARCHAR(80),
  time_min INT,
  difficulty VARCHAR(20),
  veg TINYINT(1) DEFAULT 0,
  spice_level VARCHAR(20),
  image_url VARCHAR(500),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_dish_name (name)
);

CREATE TABLE IF NOT EXISTS ingredients (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  UNIQUE KEY uniq_ingredient (name)
);

CREATE TABLE IF NOT EXISTS dish_ingredients (
  dish_id BIGINT NOT NULL,
  ingredient_id BIGINT NOT NULL,
  amount_text VARCHAR(120),
  PRIMARY KEY (dish_id, ingredient_id),
  FOREIGN KEY (dish_id) REFERENCES dishes(id) ON DELETE CASCADE,
  FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_library (
  user_id BIGINT NOT NULL,
  dish_id BIGINT NOT NULL,
  active TINYINT(1) DEFAULT 1,
  rating TINYINT,
  last_cooked_at DATE,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, dish_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (dish_id) REFERENCES dishes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS day_plan (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  date DATE NOT NULL,
  dish_id BIGINT NOT NULL,
  is_override TINYINT(1) DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_user_date (user_id, date),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (dish_id) REFERENCES dishes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS preferences (
  user_id BIGINT PRIMARY KEY,
  diet VARCHAR(20) DEFAULT 'None',
  spice_level VARCHAR(20) DEFAULT 'Medium',
  time_max INT DEFAULT 60,
  allergies TEXT,
  avoid TEXT,
  notify_time TIME DEFAULT '19:00',
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

INSERT INTO preferences (user_id) VALUES (1) ON DUPLICATE KEY UPDATE user_id=user_id;


ALTER TABLE preferences ADD COLUMN daily_suggestions TINYINT(1) DEFAULT 1;
ALTER TABLE preferences ADD COLUMN weekly_discovery TINYINT(1) DEFAULT 1;
ALTER TABLE preferences ADD COLUMN auto_suggestions TINYINT(1) DEFAULT 1;
ALTER TABLE preferences ADD COLUMN cooldown_days INT DEFAULT 4;
ALTER TABLE preferences ADD COLUMN theme VARCHAR(10) DEFAULT 'light';


CREATE INDEX idx_day_plan_user_date ON day_plan (user_id, date);
CREATE INDEX idx_day_plan_dish ON day_plan (dish_id);
