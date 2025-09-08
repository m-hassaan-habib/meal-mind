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
  daily_suggestions TINYINT(1) DEFAULT 1,
  weekly_discovery TINYINT(1) DEFAULT 1,
  auto_suggestions TINYINT(1) DEFAULT 1,
  cooldown_days INT DEFAULT 4,
  theme VARCHAR(10) DEFAULT 'light',
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discover_feed (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  week_start DATE NOT NULL,
  dish_id INT NULL,
  source VARCHAR(16) NOT NULL,
  sort_rank INT DEFAULT 0,
  name VARCHAR(255) NULL,
  image_url VARCHAR(500) NULL,
  source_url VARCHAR(500) NULL,
  time_min INT NULL,
  cuisine VARCHAR(64) NULL,
  difficulty VARCHAR(32) NULL,
  veg TINYINT(1) DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_week_dish (user_id, week_start, dish_id),
  KEY idx_user_week (user_id, week_start)
);


INSERT INTO preferences (user_id) VALUES (1) ON DUPLICATE KEY UPDATE user_id=user_id;

CREATE INDEX idx_day_plan_user_date ON day_plan (user_id, date);
CREATE INDEX idx_day_plan_dish ON day_plan (dish_id);

ALTER TABLE dishes ADD INDEX idx_dishes_name (name);
ALTER TABLE dish_ingredients ADD INDEX idx_di_ingredient (ingredient_id);
ALTER TABLE user_library ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE discover_feed ADD UNIQUE KEY uq_user_week_name (user_id, week_start, name);
