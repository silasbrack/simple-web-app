-- name: get_todos(limit)
SELECT *
FROM todos
LIMIT :limit;
