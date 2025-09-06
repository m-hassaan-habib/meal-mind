USE mealmind;

INSERT INTO dishes (name,cuisine,time_min,difficulty,veg,spice_level,image_url) VALUES
('Chicken Biryani','South Asian',60,'Medium',0,'High','/static/img/biryani.jpg'),
('Beef Qeema','South Asian',45,'Easy',0,'Medium','/static/img/placeholder.jpg'),
('Daal Tarka','South Asian',30,'Easy',1,'Medium','/static/img/placeholder.jpg'),
('Palak Paneer','South Asian',35,'Medium',1,'Medium','/static/img/placeholder.jpg'),
('Pasta Arrabbiata','Italian',25,'Easy',1,'Spicy','/static/img/placeholder.jpg'),
('Grilled Fish with Lemon','Mediterranean',20,'Easy',0,'Low','/static/img/placeholder.jpg')
ON DUPLICATE KEY UPDATE cuisine=VALUES(cuisine);

INSERT INTO ingredients (name) VALUES
('rice'),('chicken'),('onion'),('yogurt'),('spices'),('beef'),('peas'),('lentils'),('spinach'),('paneer'),('pasta'),('tomato'),('chili'),('fish'),('lemon')
ON DUPLICATE KEY UPDATE name=name;

INSERT IGNORE INTO dish_ingredients SELECT d.id, i.id, NULL FROM dishes d JOIN ingredients i ON i.name IN ('rice','chicken','onion','yogurt','spices') WHERE d.name='Chicken Biryani';
INSERT IGNORE INTO dish_ingredients SELECT d.id, i.id, NULL FROM dishes d JOIN ingredients i ON i.name IN ('beef','onion','spices') WHERE d.name='Beef Qeema';
INSERT IGNORE INTO dish_ingredients SELECT d.id, i.id, NULL FROM dishes d JOIN ingredients i ON i.name IN ('lentils','onion','spices') WHERE d.name='Daal Tarka';
INSERT IGNORE INTO dish_ingredients SELECT d.id, i.id, NULL FROM dishes d JOIN ingredients i ON i.name IN ('spinach','paneer','onion','spices') WHERE d.name='Palak Paneer';
INSERT IGNORE INTO dish_ingredients SELECT d.id, i.id, NULL FROM dishes d JOIN ingredients i ON i.name IN ('pasta','tomato','chili') WHERE d.name='Pasta Arrabbiata';
INSERT IGNORE INTO dish_ingredients SELECT d.id, i.id, NULL FROM dishes d JOIN ingredients i ON i.name IN ('fish','lemon','spices') WHERE d.name='Grilled Fish with Lemon';

INSERT IGNORE INTO user_library (user_id,dish_id,last_cooked_at) SELECT 1,id,NULL FROM dishes;
