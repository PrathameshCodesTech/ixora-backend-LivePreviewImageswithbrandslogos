import redis
r = redis.Redis(host='localhost', port=6379, db=0)
try:
    r.set('test', 'hello')
    print("Redis connected:", r.get('test'))
except Exception as e:
    print("Redis error:", e)