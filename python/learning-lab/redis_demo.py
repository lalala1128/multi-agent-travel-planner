from redis import Redis


client = Redis(
    host="127.0.0.1",
    port=6380,
    db=0,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
)

try:
    print("连接结果：", client.ping())

    key = "travel:demo:city"

    client.set(key, "首尔", ex=60)

    city = client.get(key)
    remaining_seconds = client.ttl(key)

    print("读取结果：", city)
    print("剩余有效期：", remaining_seconds)

finally:
    client.close()