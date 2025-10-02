-- name: get_news(limit, offset, max_published_time)
SELECT id, title, text, published
FROM news_item
WHERE language = 'english'
  AND (published < :max_published_time)
ORDER BY published DESC, id ASC
LIMIT :limit
OFFSET :offset;

-- name: search_news(query, limit)
SELECT title, text
FROM news_item_fts(:query)
LIMIT :limit;

-- name: get_categories_for_news(news_item_id)
SELECT nic.category_id, c.name AS category
FROM news_item_category AS nic
INNER JOIN category AS c
  ON c.id = nic.category_id
WHERE nic.news_item_id = :news_item_id;

-- name: get_categories(limit)
SELECT id, name AS category
FROM category
ORDER BY id
LIMIT :limit;

