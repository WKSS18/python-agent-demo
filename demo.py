print("测试")

a = [1, 2, 3]
a.append(23)
print(a)

c = {"x": 2, "y": 4}


def test():
    for i in c:
        print(i, "------", c[i])


# test()


def addItem(item, arr=None):

    if arr is None:
        arr = []

    arr.append(item)
    return arr


print(addItem(1))
print(addItem(2))


def add_item(item, arr=[]):
    arr.append(item)
    return arr


print(add_item(3))
print(add_item(5))


def arg_demo(*args, **kwargs):
    print(args)
    print(kwargs)


arg_demo(3, 4, "STRING", name="tom", age=45)


for x in [3, 6, 8]:
    if x > 4:
        print(x)


def read_data():
    # for i in range(10):
    #     yield i
    yield from range(10)


gen = read_data()
print(next(gen))
print(next(gen))
print(next(gen))
print(next(gen))
print(next(gen))
print(next(gen))


def log(func):
    def wrapper(*args, **kwargs):
        print("start")
        result = func(*args, **kwargs)
        print("end")
        return result

    return wrapper


# 装饰器


@log
def hello():
    print(hello)
    print("hello")


hello()

with open("./requirements.txt") as f:
    data = f.read()
    print(data)


# 继承
class DocumentService:
    def __init__(self, repository, embedding_service, vector_service):
        self.repository = repository
        self.embedding_service = embedding_service
        self.vector_service = vector_service

    def test(age):
        print(age, "----")


print(DocumentService.test(34))


ca = {"name": 34}
ba = {"name": 34}
print(ca["name"] == ba["name"])


import asyncio


async def request():
    await asyncio.sleep(1)
    return "ok"


async def main():
    result = await request()
    print(result)


asyncio.run(main())
