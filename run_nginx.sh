# Workaround to produce ETag headers for soundtouch device compatibility
# See also: https://github.com/deborahgu/soundcork/issues/129

docker run --rm --name nginx-ETag -p 8002:80 -v $(pwd)/nginx-ETag.conf:/etc/nginx/conf.d/default.conf:ro nginx
