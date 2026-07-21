# Python 面试题 30 道：详解、答案与代码

> 适用方向：Python 后端、FastAPI、AI 应用开发。  
> 建议复习方法：先只看题目口述 1–2 分钟，再对照“参考回答”补充，最后手写代码。

## 一、Python 语言基础

## 1. Python 中的可变对象和不可变对象有什么区别？

### 参考回答

Python 变量保存的是对象引用，而不是将值直接装在变量中。

- 可变对象可在身份 `id` 不变的情况下修改内容，例如 `list`、`dict`、`set`。
- 不可变对象创建后不能原地修改，所谓“修改”实际是创建新对象并重新绑定，例如 `int`、`float`、`str`、`tuple`、`frozenset`。
- 函数参数传递可理解为“对象引用的赋值”。函数内对可变对象做原地修改，调用者可见；将局部参数重新绑定到新对象，调用者不受影响。

```python
def change(items: list[int], number: int) -> None:
    items.append(3)  # 原地修改同一个 list
    number += 1      # 创建新 int，只重绑定局部变量


values = [1, 2]
count = 10
change(values, count)

print(values)  # [1, 2, 3]
print(count)   # 10
```

### 常见追问

`tuple` 不可变是指 tuple 保存的元素引用不能被替换，不代表元素指向的可变对象不能变。

```python
data = ([1, 2], "python")
data[0].append(3)
print(data)  # ([1, 2, 3], 'python')
```

## 2. `==` 和 `is` 有什么区别？

### 参考回答

- `==` 比较值是否相等，本质上调用 `__eq__`。
- `is` 比较两个引用是否指向同一个对象。
- 判断 `None` 应使用 `is None` 或 `is not None`，因为 `None` 是单例，且不会受自定义 `__eq__` 干扰。

```python
first = [1, 2]
second = [1, 2]
alias = first

print(first == second)  # True，内容相等
print(first is second)  # False，不是同一对象
print(first is alias)   # True
```

不要因为小整数缓存或字符串驻留使某些 `is` 比较“恰好成功”，就用 `is` 比较普通值。这些是实现优化，不应成为业务逻辑的依据。

## 3. 浅拷贝和深拷贝有什么区别？

### 参考回答

- 赋值 `b = a` 不会拷贝，只是增加一个引用。
- 浅拷贝创建新外层容器，但内层对象仍然共享。
- 深拷贝递归复制嵌套对象，并通过 memo 处理循环引用和重复引用。

```python
import copy

source = [[1, 2], [3, 4]]
shallow = copy.copy(source)
deep = copy.deepcopy(source)

source[0].append(99)

print(shallow)  # [[1, 2, 99], [3, 4]]
print(deep)     # [[1, 2], [3, 4]]
```

深拷贝可能消耗大量时间和内存，也不是所有对象都适合深拷贝，例如文件句柄、锁和数据库连接。实际开发中应先明确需要隔离哪一层数据。

## 4. 为什么不建议使用可变对象作为函数默认参数？

### 参考回答

默认参数在函数定义时求值一次，而不是每次调用时重新创建。因此多次调用会共享同一个 list 或 dict。

```python
# 错误示例
def collect_bad(value: int, result: list[int] = []) -> list[int]:
    result.append(value)
    return result


print(collect_bad(1))  # [1]
print(collect_bad(2))  # [1, 2]
```

正确做法是使用 `None` 作为哨兵值：

```python
def collect(value: int, result: list[int] | None = None) -> list[int]:
    if result is None:
        result = []
    result.append(value)
    return result
```

如果确实想利用共享状态做缓存，也应明确使用 `functools.lru_cache` 或封装类，不要隐式借用默认参数。

## 5. List、Tuple、Set 和 Dict 如何选择？

### 参考回答

| 结构 | 特点 | 常见场景 | 平均查找复杂度 |
| --- | --- | --- | --- |
| list | 有序、可变、允许重复 | 需要按位置访问的序列 | 按值 `O(n)`，按索引 `O(1)` |
| tuple | 有序、不可变 | 固定记录、多返回值、可哈希键 | 按索引 `O(1)` |
| set | 无重复、无索引 | 去重、成员测试、集合运算 | 成员测试平均 `O(1)` |
| dict | key-value，key 唯一 | 索引、配置、计数、映射 | 按 key 平均 `O(1)` |

```python
from collections import Counter

words = ["python", "mysql", "python"]
unique_words = set(words)
counts = Counter(words)

print(unique_words)      # {'python', 'mysql'}
print(counts["python"])  # 2
```

Set 和 Dict 基于哈希表，最坏情况不保证 `O(1)`。key 必须可哈希，通常要求其哈希值在生命周期内稳定。

## 6. 列表推导式和生成器表达式有什么区别？

### 参考回答

- 列表推导式 `[...]` 会立即计算并把所有结果放入内存。
- 生成器表达式 `(...)` 是惰性的，每次迭代生成一个值。
- 数据量小且需要多次遍历或随机访问时用 list；数据量大、流式处理或只遍历一次时用 generator。

```python
squares_list = [number * number for number in range(1_000_000)]
squares_generator = (number * number for number in range(1_000_000))

# sum 可以直接消费生成器，无需构造百万元素列表
total = sum(number * number for number in range(1_000_000))
```

生成器通常只能消费一次，不支持 `len()` 和按索引取值。

## 7. 可迭代对象、迭代器和生成器有什么关系？

### 参考回答

- Iterable 实现 `__iter__()`，可被 `for` 遍历。
- Iterator 实现 `__iter__()` 和 `__next__()`；没有下一个值时抛出 `StopIteration`。
- Generator 是一种特殊迭代器，通常由包含 `yield` 的函数创建，Python 自动保存暂停位置和局部状态。

```python
class Countdown:
    def __init__(self, start: int) -> None:
        self.current = start

    def __iter__(self) -> "Countdown":
        return self

    def __next__(self) -> int:
        if self.current <= 0:
            raise StopIteration
        value = self.current
        self.current -= 1
        return value


for value in Countdown(3):
    print(value)  # 3, 2, 1
```

`for item in iterable` 大致等价于先执行 `iterator = iter(iterable)`，然后反复调用 `next(iterator)`，直到捕获 `StopIteration`。

## 8. `yield` 和 `yield from` 是什么？

### 参考回答

`yield` 会产生一个值并暂停函数，下次迭代从暂停处继续。`yield from` 将迭代委托给另一个 iterable，能简化嵌套生成器。

```python
from collections.abc import Iterator


def read_chunks(data: bytes, size: int) -> Iterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start:start + size]


def combined() -> Iterator[int]:
    yield from range(3)
    yield from range(10, 13)


print(list(read_chunks(b"abcdefgh", 3)))
# [b'abc', b'def', b'gh']
print(list(combined()))
# [0, 1, 2, 10, 11, 12]
```

生成器适合大文件、数据库游标、分页 API 和流式 ETL，关键价值是边生产边消费，而不是先将数据全部载入内存。

## 9. 装饰器的原理是什么？如何编写带参数的装饰器？

### 参考回答

函数是一等对象，可被当作参数传入和返回。`@decorator` 本质上是 `target = decorator(target)`。带参数装饰器多一层函数，用于先接收配置。

```python
from collections.abc import Callable
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def log_time(label: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = perf_counter() - started
                print(f"{label}: {elapsed:.4f}s")
        return wrapper
    return decorator


@log_time("calculate")
def add(left: int, right: int) -> int:
    return left + right
```

`functools.wraps` 会保留原函数的 `__name__`、`__doc__` 和其他元数据，对 FastAPI 这类需要检查函数签名的框架尤其重要。

## 10. 什么是闭包？如何解决循环中的延迟绑定问题？

### 参考回答

闭包是一个函数和它所捕获的外层作用域变量的组合。Python 闭包中的自由变量默认是延迟查找：函数真正执行时才读取当前值。

```python
# 错误：三个 lambda 都在调用时读取最终的 i=2
bad_functions = [lambda: i for i in range(3)]
print([func() for func in bad_functions])  # [2, 2, 2]

# 正确：利用默认参数在定义时绑定当前值
functions = [lambda value=i: value for i in range(3)]
print([func() for func in functions])  # [0, 1, 2]
```

闭包常用于装饰器、函数工厂和小型状态封装。状态复杂时通常使用类更易维护。

## 11. Python 的 LEGB 作用域规则是什么？

### 参考回答

Python 查找名称的顺序是：

1. Local：当前函数局部作用域。
2. Enclosing：外层嵌套函数作用域。
3. Global：当前模块全局作用域。
4. Built-in：Python 内置名称。

```python
count = 1


def outer() -> callable:
    count = 2

    def inner() -> int:
        nonlocal count
        count += 1
        return count

    return inner


counter = outer()
print(counter())  # 3
print(counter())  # 4
print(count)      # 1，模块全局变量未变
```

- `nonlocal` 修改最近的 enclosing 作用域变量。
- `global` 修改模块全局变量。
- 应尽量减少可变全局状态，因为它会增加耦合和并发风险。

## 12. 上下文管理器是什么？

### 参考回答

上下文管理器为资源提供“进入”和“退出”边界，保证即使中间发生异常，清理逻辑也会执行。类可实现 `__enter__`/`__exit__`，函数可使用 `contextlib.contextmanager`。

```python
from contextlib import contextmanager
from collections.abc import Iterator
from time import perf_counter


@contextmanager
def timer(label: str) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        print(f"{label}: {perf_counter() - started:.4f}s")


with timer("work"):
    total = sum(range(1_000_000))
```

常见场景包括文件、数据库事务、锁、临时文件和测试 patch。`__exit__` 返回真值可抑制异常，业务代码中应谨慎使用，避免静默吞掉错误。

## 13. Python 异常处理的最佳实践是什么？

### 参考回答

- 只捕获能处理的具体异常，避免空的 `except:` 或过宽的 `except Exception:`。
- `else` 在没有异常时执行，可减小 try 块范围。
- `finally` 用于无论成功失败都需要执行的清理。
- 使用 `raise ... from error` 保留异常链。
- 不要同时记录又在每层原样抛出，否则会产生重复日志。

```python
class ConfigError(RuntimeError):
    """配置无法被正确解析。"""


def parse_port(raw_value: str) -> int:
    try:
        port = int(raw_value)
    except ValueError as error:
        raise ConfigError(f"invalid port: {raw_value!r}") from error
    else:
        if not 1 <= port <= 65535:
            raise ConfigError("port must be between 1 and 65535")
        return port
```

自定义异常应表达领域语义，例如 `InsufficientBalanceError`，而不是仅为了“换个名字”包装所有底层异常。

## 14. `*args` 和 `**kwargs` 是什么？参数顺序如何理解？

### 参考回答

- `*args` 收集多余位置参数为 tuple。
- `**kwargs` 收集多余关键字参数为 dict。
- `/` 之前是仅位置参数，`*` 之后是仅关键字参数。

```python
def request(
    path: str,
    /,
    method: str = "GET",
    *,
    timeout: float = 5.0,
    **headers: str,
) -> dict[str, object]:
    return {
        "path": path,
        "method": method,
        "timeout": timeout,
        "headers": headers,
    }


result = request(
    "/health",
    method="GET",
    timeout=2.0,
    Authorization="Bearer token",
)
```

在装饰器和转发函数中常用 `*args, **kwargs`，但业务 API 如果过度使用会降低类型可读性。能显式声明的参数应尽量显式声明。

## 15. Python 类的实例方法、类方法和静态方法有什么区别？

### 参考回答

- 实例方法首参数是 `self`，用于访问实例状态。
- 类方法用 `@classmethod`，首参数是 `cls`，常用作可继承的备选构造器。
- 静态方法用 `@staticmethod`，不自动接收 `self` 或 `cls`，表示逻辑与该类概念相关，但不需要对象状态。

```python
from dataclasses import dataclass


@dataclass
class User:
    email: str

    def domain(self) -> str:
        return self.email.rsplit("@", maxsplit=1)[-1]

    @classmethod
    def from_username(cls, username: str, domain: str) -> "User":
        return cls(email=f"{username}@{domain}")

    @staticmethod
    def is_valid_email(value: str) -> bool:
        return "@" in value and not value.startswith("@")


user = User.from_username("alice", "example.com")
print(user.domain())
```

如果一个静态方法与类的职责关系很弱，就应移到模块级函数，不要为了“面向对象”强行放进类。

## 二、面向对象、类型和内存

## 16. `@property` 和描述符是什么？

### 参考回答

`property` 让调用者以属性语法访问方法逻辑，适合校验、计算属性和保持 API 兼容。它本身就是一种描述符。实现 `__get__`、`__set__` 或 `__delete__` 的对象称为描述符。

```python
class Account:
    def __init__(self, balance: int = 0) -> None:
        self.balance = balance

    @property
    def balance(self) -> int:
        return self._balance

    @balance.setter
    def balance(self, value: int) -> None:
        if value < 0:
            raise ValueError("balance cannot be negative")
        self._balance = value
```

描述符是 ORM 字段、数据校验框架和属性管理的基础机制。但 property 不宜执行昂贵 IO，否则调用者看到属性访问时很难意识到它会查数据库或请求网络。

## 17. Python 多继承的 MRO 和 `super()` 如何工作？

### 参考回答

MRO 是方法解析顺序。Python 使用 C3 线性化生成一个一致顺序。`super()` 不是简单表示“直接父类”，而是沿当前类的 MRO 调用下一个实现。

```python
class Base:
    def process(self) -> list[str]:
        return ["Base"]


class LoggingMixin(Base):
    def process(self) -> list[str]:
        return ["Logging"] + super().process()


class MetricsMixin(Base):
    def process(self) -> list[str]:
        return ["Metrics"] + super().process()


class Service(LoggingMixin, MetricsMixin):
    pass


print(Service.mro())
print(Service().process())  # ['Logging', 'Metrics', 'Base']
```

协作式多继承要求链上各类都正确调用 `super()`，并使用兼容的方法签名。业务类层级过于复杂时，优先考虑组合而非多继承。

## 18. `dataclass` 解决什么问题？

### 参考回答

`@dataclass` 根据类型注解自动生成 `__init__`、`__repr__`、`__eq__` 等样板代码，适合以数据为主的领域对象。

```python
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class OrderItem:
    sku: str
    unit_price: int
    quantity: int = 1
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return self.unit_price * self.quantity
```

- `frozen=True` 禁止普通属性赋值，用于表达值对象，但不是安全边界。
- `slots=True` 避免每个实例默认持有 `__dict__`，大量对象时可减少内存，但会限制动态属性。
- 可变默认值要用 `default_factory`。

Dataclass 不会自动做运行时类型校验；需要 API 输入校验时，Pydantic 更合适。

## 19. Python 类型注解在运行时会强制生效吗？

### 参考回答

默认不会。类型注解主要供 IDE、mypy、pyright 等静态工具使用。Python 运行时仍允许传入其他类型，除非代码或框架主动校验。

```python
from typing import Protocol, TypeVar


class SupportsClose(Protocol):
    def close(self) -> None: ...


T = TypeVar("T", bound=SupportsClose)


def close_resource(resource: T) -> T:
    resource.close()
    return resource
```

`Protocol` 支持结构化子类型：对象只要拥有约定方法就可以被视为满足协议，不需要显式继承。这适合通过接口解耦实现。

Pydantic 会利用类型注解在运行时校验和转换数据，这是框架行为，不是 Python 注解自带的强制性。

## 20. CPython 如何管理内存？什么是循环引用？

### 参考回答

CPython 主要使用引用计数：当引用数降到 0 时对象通常立即释放。但引用计数不能单独处理循环引用，因此 CPython 还有分代循环垃圾回收器。

```python
import gc
import weakref


class Node:
    def __init__(self) -> None:
        self.next: "Node | None" = None


first = Node()
second = Node()
first.next = second
second.next = first  # 循环引用

reference = weakref.ref(first)
del first, second
gc.collect()

print(reference())  # None，循环回收器已处理
```

内存泄漏不一定是“垃圾回收失效”，更常见的是全局缓存、事件回调、任务列表或连接池仍保持着对象引用。排查时可使用 `tracemalloc`、堆快照和对象增长对比。

## 三、并发与异步

## 21. 什么是 GIL？它对 Python 并发有什么影响？

### 参考回答

GIL 是 CPython 中保护 Python 对象内部状态的全局解释器锁。在传统 GIL 构建中，同一时刻通常只有一个线程执行 Python 字节码。

- CPU 密集型纯 Python 代码很难通过多线程获得多核加速，常用多进程、C 扩展或向量化库。
- IO 密集型任务在等待网络、文件或数据库时会释放 GIL，多线程仍然能提升吞吐。
- 许多 NumPy 等 C 扩展会在重计算时释放 GIL。

GIL 不等于线程安全。复合操作仍可能在字节码之间切换，IO 也会释放 GIL，所以共享可变状态仍需要锁或消息传递。

## 22. 线程、进程和 asyncio 如何选择？

### 参考回答

| 方式 | 适合场景 | 优点 | 代价 |
| --- | --- | --- | --- |
| Thread | 同步 IO 密集、阻塞库 | 共享内存，改造成本低 | 锁竞争，CPU 密集受 GIL 限制 |
| Process | CPU 密集 | 利用多核，内存隔离 | 启动和 IPC 成本高，对象需序列化 |
| asyncio | 大量并发网络 IO | 单线程可管理大量等待任务 | 要求调用链使用异步库，CPU/阻塞 IO 会阻塞事件循环 |

```python
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor


def blocking_io(url: str) -> str:
    # 代表同步 HTTP 请求
    return url


def cpu_work(number: int) -> int:
    return sum(value * value for value in range(number))


with ThreadPoolExecutor(max_workers=8) as pool:
    io_results = list(pool.map(blocking_io, ["a", "b", "c"]))

with ProcessPoolExecutor() as pool:
    cpu_results = list(pool.map(cpu_work, [100_000] * 4))
```

选型应基于瓶颈测量，而不是看到“并发”就全部改成 async。

## 23. `async`/`await` 和事件循环如何工作？

### 参考回答

`async def` 创建协程函数，调用它返回协程对象。`await` 等待可等待对象，当前协程在等待 IO 时将控制权交回事件循环，事件循环再运行其他已就绪任务。

```python
import asyncio


async def fetch(name: str, delay: float) -> str:
    await asyncio.sleep(delay)  # 模拟非阻塞 IO
    return name


async def main() -> None:
    async with asyncio.TaskGroup() as group:
        first = group.create_task(fetch("first", 0.2))
        second = group.create_task(fetch("second", 0.1))

    print(first.result(), second.result())


asyncio.run(main())
```

`asyncio.sleep()` 会让出事件循环，`time.sleep()` 会阻塞线程。在 async 函数中调用 `requests`、同步 SQLAlchemy 或 CPU 密集代码，会让整个事件循环卡住。应改用异步库，或通过 `asyncio.to_thread()` 隔离少量阻塞调用。

## 24. 什么是竞态条件？Lock 和 RLock 有什么区别？

### 参考回答

竞态条件是多个执行单元的结果依赖不可控执行顺序。“读取→修改→写回”是复合操作，通常需要互斥。

```python
from threading import Lock, Thread


class Counter:
    def __init__(self) -> None:
        self._value = 0
        self._lock = Lock()

    def increment(self) -> None:
        with self._lock:
            self._value += 1

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


counter = Counter()
threads = [Thread(target=lambda: [counter.increment() for _ in range(10_000)]) for _ in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()

print(counter.value)  # 40000
```

- `Lock` 被同一线程再次获取时会死锁。
- `RLock` 是可重入锁，同一线程可多次获取，但必须对应次数地释放。
- 锁的临界区要尽可能小，避免持锁进行慢 IO。

## 25. 如何用 Queue 实现线程安全的生产者-消费者？

### 参考回答

Queue 封装了必要的同步，通过消息传递取代多个线程直接修改共享容器。有界 Queue 还可实现背压，避免生产速度远大于消费速度时内存无限增长。

```python
from queue import Queue
from threading import Thread

STOP = object()


def worker(queue: Queue[object]) -> None:
    while True:
        item = queue.get()
        try:
            if item is STOP:
                return
            print(f"processing {item}")
        finally:
            queue.task_done()


tasks: Queue[object] = Queue(maxsize=100)
thread = Thread(target=worker, args=(tasks,))
thread.start()

for value in range(5):
    tasks.put(value)
tasks.put(STOP)

tasks.join()
thread.join()
```

`task_done()` 必须与每次成功 `get()` 匹配，否则 `join()` 可能永远等待。多个 worker 时通常要为每个 worker 放入一个停止哨兵。

## 四、FastAPI、数据库与安全

## 26. FastAPI 的依赖注入如何工作？

### 参考回答

FastAPI 根据 `Depends()` 构建依赖图，解析子依赖，并在同一请求内默认缓存相同依赖的结果。包含 `yield` 的依赖可在响应后执行清理逻辑。

```python
from collections.abc import Generator
from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

app = FastAPI()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_service(db: Session = Depends(get_db)) -> "UserService":
    return UserService(db)


@app.get("/users/{user_id}")
def get_user(user_id: int, service: "UserService" = Depends(get_service)):
    return service.get(user_id)
```

优点：

- 鉴权、数据库 Session、配置和 Service 组装可复用。
- 路由函数只声明需求，降低与创建细节的耦合。
- 测试可使用 `app.dependency_overrides` 替换真实数据库或鉴权依赖。

## 27. Pydantic Model 和 SQLAlchemy Model 有什么区别？

### 参考回答

- Pydantic Model 是数据校验、转换和序列化模型，常作为 API DTO。
- SQLAlchemy Model 是持久化模型，跟踪对象状态并映射表、列、外键和关系。
- 两者分开可防止敏感字段泄露，并让 API 合同不必与表结构一比一绑定。

```python
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class UserRead(BaseModel):
    id: int
    email: EmailStr

    # 允许从 ORM 对象属性构建响应
    model_config = ConfigDict(from_attributes=True)
```

Create、Update 和 Read 应定义不同 Schema。例如 `hashed_password` 只存在 ORM，不应出现在 Read Schema；Update Schema 的字段可为可选，配合 `exclude_unset=True` 实现部分更新。

## 28. SQLAlchemy Session、事务和 N+1 问题分别是什么？

### 参考回答

Session 是 Unit of Work 和 Identity Map：它跟踪 ORM 对象变化，管理 flush/commit/rollback，并在同一 Session 中尽量保证同一数据库行对应同一 Python 对象。Session 不是数据库连接本身，它在需要时从 Engine 连接池获取连接。

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload


def create_user(db: Session, email: str) -> User:
    user = User(email=email)
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise


# 用 selectinload 批量预加载 notes，避免遍历用户时每人再查一次
query = select(User).options(selectinload(User.notes))
users = list(db.scalars(query))
```

N+1 问题是先查 1 次父对象列表，然后访问每个父对象的懒加载关系时又执行 N 次 SQL。解决方式包括 `selectinload`、`joinedload`、显式 join 和批量查询。

- `selectinload` 通常执行父查询 + `WHERE child.fk IN (...)` 子查询，适合一对多。
- `joinedload` 用 JOIN 一次取回，可能造成父行重复和数据膨胀。

## 29. 密码存储和 JWT 鉴权有哪些安全要点？

### 参考回答

密码：

- 不存明文，不使用可逆加密。
- 使用 Argon2id、bcrypt 或 scrypt 这类专用密码哈希。
- 每个密码使用随机 salt；现代密码库会自动处理。
- 选择适当计算成本，并支持未来 rehash。
- 登录接口要限流，必要时增加 MFA。

JWT：

- 验证签名、限定允许的 algorithm，校验 `exp`、`iss`、`aud` 等必要声明。
- Access Token 应短效，Refresh Token 应支持轮换和撤销。
- Payload 只是 Base64URL 编码，不是加密，不放密码等敏感信息。
- 通过 HTTPS 传输，Web 中要根据存储方式考虑 XSS 和 CSRF。

```python
from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_token(user_id: int, secret: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    return jwt.encode(payload, secret, algorithm="HS256")
```

HS256 使用同一密钥签名和验签，适合单一可信边界；多服务只需验签时可使用 RS256/EdDSA，让签发方保留私钥，其他服务只分发公钥。

## 30. 手写一个 LRU Cache，并说明复杂度

### 题目

实现 `get(key)` 和 `put(key, value)`，两者平均时间复杂度都要求 `O(1)`。容量满时删除最久未使用的键。

### 思路

- Hash Map 用于 `O(1)` 按 key 找到节点。
- 双向链表维护使用顺序，支持 `O(1)` 删除任意节点和移到头部。
- 头部表示最近使用，尾部表示最久未使用。

Python 生产代码可以直接用 `OrderedDict`：

```python
from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._data: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key, last=True)
        return self._data[key]

    def put(self, key: K, value: V) -> None:
        if key in self._data:
            self._data.move_to_end(key, last=True)
        self._data[key] = value

        if len(self._data) > self.capacity:
            self._data.popitem(last=False)


cache: LRUCache[str, int] = LRUCache(2)
cache.put("a", 1)
cache.put("b", 2)
print(cache.get("a"))  # 1，a 变成最近使用
cache.put("c", 3)      # 淘汰 b
print(cache.get("b"))  # None
```

### 复杂度

- `get`：平均 `O(1)`。
- `put`：平均 `O(1)`。
- 空间：`O(capacity)`。

### 常见追问

1. 并发安全：当多线程共享缓存时，`get` 也会修改顺序，因此 `get` 和 `put` 都需要在同一把锁下执行。
2. 过期时间：为节点增加 `expires_at`，读取时惰性删除，也可搭配最小堆或定时清理。
3. 多进程：进程内 LRU 不共享，需要 Redis 等外部缓存。
4. 缓存穿透/击穿/雪崩：可使用空值缓存、singleflight/互斥锁、TTL 随机抖动和限流降级。

## 五、快速复习索引

### Python 基础必会

- 可变/不可变、引用传递、`==`/`is`。
- 浅拷贝/深拷贝、可变默认参数。
- 容器选型和基本复杂度。
- Iterable、Iterator、Generator、`yield`。
- 装饰器、闭包、LEGB、上下文管理器。

### 高级 Python 必会

- property/描述符、MRO/`super()`、dataclass。
- 类型注解不默认强制，Protocol 表达结构化协议。
- CPython 引用计数、循环回收和 GIL。

### 后端必会

- 线程、进程、asyncio 选型。
- 竞态条件、锁和 Queue。
- FastAPI 依赖注入和 sync/async 边界。
- Pydantic DTO 与 SQLAlchemy ORM 分层。
- Session、事务、rollback 和 N+1。
- 密码哈希、JWT 鉴权和常见安全边界。

## 六、面试回答技巧

1. 先用一句话给结论，再讲原理，最后结合项目。
2. 不要只背 API，要说选型条件和代价。
3. 遇到复杂度题，同时说平均/最坏情况和空间复杂度。
4. 遇到并发题，先区分 CPU 密集和 IO 密集。
5. 遇到框架题，说清框架帮你管理的生命周期和边界。
6. 不确定时明确边界，例如“以 CPython 为例”、“平均情况下”，不要把实现细节说成语言规范的永久保证。
