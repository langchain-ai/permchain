import asyncio
import operator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, AsyncIterator, Generator

import pytest
from langchain.schema.runnable import RunnablePassthrough
from pytest_mock import MockerFixture

from permchain import Channel, Pregel
from permchain.channels.base import InvalidUpdateError
from permchain.channels.binop import BinaryOperatorAggregate
from permchain.channels.context import Context
from permchain.channels.last_value import LastValue
from permchain.channels.topic import Topic
from permchain.checkpoint.memory import MemoryCheckpoint
from permchain.pregel.reserved import ReservedChannels


async def test_invoke_single_process_in_out(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain = Channel.subscribe_to("input") | add_one | Channel.write_to("output")

    app = Pregel(
        chains={
            "one": chain,
        },
        channels={
            "input": LastValue(int),
            "output": LastValue(int),
        },
        input="input",
        output="output",
    )

    assert app.input_schema.schema() == {"title": "PregelInput", "type": "integer"}
    assert app.output_schema.schema() == {"title": "PregelOutput", "type": "integer"}
    assert await app.ainvoke(2) == 3


async def test_invoke_single_process_in_out_implicit_channels(
    mocker: MockerFixture
) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain = Channel.subscribe_to("input") | add_one | Channel.write_to("output")

    app = Pregel(chains={"one": chain})

    assert app.input_schema.schema() == {"title": "PregelInput"}
    assert app.output_schema.schema() == {"title": "PregelOutput"}
    assert await app.ainvoke(2) == 3


async def test_invoke_single_process_in_write_kwargs(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain = (
        Channel.subscribe_to("input")
        | add_one
        | Channel.write_to("output", fixed=5, output_plus_one=lambda x: x + 1)
    )

    app = Pregel(chains={"one": chain}, output=["output", "fixed", "output_plus_one"])

    assert app.input_schema.schema() == {"title": "PregelInput"}
    assert app.output_schema.schema() == {
        "title": "PregelOutput",
        "type": "object",
        "properties": {
            "output": {"title": "Output"},
            "fixed": {"title": "Fixed"},
            "output_plus_one": {"title": "Output Plus One"},
        },
    }
    assert await app.ainvoke(2) == {"output": 3, "fixed": 5, "output_plus_one": 4}


async def test_invoke_single_process_in_out_reserved_is_last(
    mocker: MockerFixture
) -> None:
    add_one = mocker.Mock(side_effect=lambda x: {**x, "input": x["input"] + 1})

    chain = (
        Channel.subscribe_to(["input"]).join([ReservedChannels.is_last_step])
        | add_one
        | Channel.write_to("output")
    )

    app = Pregel(chains={"one": chain})

    assert app.input_schema.schema() == {"title": "PregelInput"}
    assert app.output_schema.schema() == {"title": "PregelOutput"}
    assert await app.ainvoke(2) == {"input": 3, "is_last_step": False}
    assert await app.ainvoke(2, {"recursion_limit": 1}) == {
        "input": 3,
        "is_last_step": True,
    }


async def test_invoke_single_process_in_out_reserved_id_key() -> None:
    chain = Channel.subscribe_to(["input"]).join(
        [ReservedChannels.idempotency_key]
    ) | Channel.write_to("output")

    app = Pregel(chains={"one": chain})

    assert app.input_schema.schema() == {"title": "PregelInput"}
    assert app.output_schema.schema() == {"title": "PregelOutput"}
    assert await app.ainvoke(2) == {
        "input": 2,
        "idempotency_key": "b85046bb798101e60bbe82d15e18fd530eadb2c0064114ec4fae1de68d57174b",
    }
    assert await app.ainvoke(2) == {
        "input": 2,
        "idempotency_key": "b85046bb798101e60bbe82d15e18fd530eadb2c0064114ec4fae1de68d57174b",
    }
    assert await app.ainvoke(3) == {
        "input": 3,
        "idempotency_key": "5d45520557a38c1bb2e12b4e09161d5c095c38e92df5ea914e076177f117863c",
    }


async def test_invoke_single_process_in_out_dict(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain = Channel.subscribe_to("input") | add_one | Channel.write_to("output")

    app = Pregel(
        chains={
            "one": chain,
        },
        output=["output"],
    )

    assert app.input_schema.schema() == {"title": "PregelInput"}
    assert app.output_schema.schema() == {
        "title": "PregelOutput",
        "type": "object",
        "properties": {"output": {"title": "Output"}},
    }
    assert await app.ainvoke(2) == {"output": 3}


async def test_invoke_single_process_in_dict_out_dict(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain = Channel.subscribe_to("input") | add_one | Channel.write_to("output")

    app = Pregel(
        chains={
            "one": chain,
        },
        input=["input"],
        output=["output"],
    )

    assert app.input_schema.schema() == {
        "title": "PregelInput",
        "type": "object",
        "properties": {"input": {"title": "Input"}},
    }
    assert app.output_schema.schema() == {
        "title": "PregelOutput",
        "type": "object",
        "properties": {"output": {"title": "Output"}},
    }
    assert await app.ainvoke({"input": 2}) == {"output": 3}


async def test_invoke_two_processes_in_out(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain_one = Channel.subscribe_to("input") | add_one | Channel.write_to("inbox")
    chain_two = (
        Channel.subscribe_to_each("inbox") | add_one | Channel.write_to("output")
    )

    app = Pregel(
        chains={"chain_one": chain_one, "chain_two": chain_two},
        channels={"inbox": Topic(int)},
    )

    assert await app.ainvoke(2) == 4


async def test_invoke_two_processes_in_dict_out(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain_one = Channel.subscribe_to("input") | add_one | Channel.write_to("inbox")
    chain_two = (
        Channel.subscribe_to_each("inbox") | add_one | Channel.write_to("output")
    )

    pubsub = Pregel(
        chains={"chain_one": chain_one, "chain_two": chain_two},
        channels={"inbox": Topic(int)},
        input=["input", "inbox"],
    )

    # [12 + 1, 2 + 1 + 1]
    assert [c async for c in pubsub.astream({"input": 2, "inbox": 12})] == [13, 4]


async def test_batch_two_processes_in_out() -> None:
    async def add_one_with_delay(inp: int) -> int:
        await asyncio.sleep(inp / 10)
        return inp + 1

    chain_one = (
        Channel.subscribe_to("input") | add_one_with_delay | Channel.write_to("one")
    )
    chain_two = (
        Channel.subscribe_to("one") | add_one_with_delay | Channel.write_to("output")
    )

    app = Pregel(
        chains={"chain_one": chain_one, "chain_two": chain_two},
        channels={"one": LastValue(int)},
    )

    assert await app.abatch([3, 2, 1, 3, 5]) == [5, 4, 3, 5, 7]


async def test_invoke_many_processes_in_out(mocker: MockerFixture) -> None:
    test_size = 100
    add_one = mocker.Mock(side_effect=lambda x: x + 1)

    chains = {"-1": Channel.subscribe_to("input") | add_one | Channel.write_to("-1")}
    for i in range(test_size - 2):
        chains[str(i)] = (
            Channel.subscribe_to(str(i - 1)) | add_one | Channel.write_to(str(i))
        )
    chains["last"] = Channel.subscribe_to(str(i)) | add_one | Channel.write_to("output")

    app = Pregel(chains=chains)

    # No state is left over from previous invocations
    for _ in range(10):
        assert await app.ainvoke(2, {"recursion_limit": test_size}) == 2 + test_size

    # Concurrent invocations do not interfere with each other
    assert await asyncio.gather(
        *(app.ainvoke(2, {"recursion_limit": test_size}) for _ in range(10))
    ) == [2 + test_size for _ in range(10)]


async def test_batch_many_processes_in_out(mocker: MockerFixture) -> None:
    test_size = 100
    add_one = mocker.Mock(side_effect=lambda x: x + 1)

    chains = {"-1": Channel.subscribe_to("input") | add_one | Channel.write_to("-1")}
    for i in range(test_size - 2):
        chains[str(i)] = (
            Channel.subscribe_to(str(i - 1)) | add_one | Channel.write_to(str(i))
        )
    chains["last"] = Channel.subscribe_to(str(i)) | add_one | Channel.write_to("output")

    app = Pregel(chains=chains)

    # No state is left over from previous invocations
    for _ in range(3):
        # Then invoke pubsub
        assert await app.abatch([2, 1, 3, 4, 5], {"recursion_limit": test_size}) == [
            2 + test_size,
            1 + test_size,
            3 + test_size,
            4 + test_size,
            5 + test_size,
        ]

    # Concurrent invocations do not interfere with each other
    assert await asyncio.gather(
        *(app.abatch([2, 1, 3, 4, 5], {"recursion_limit": test_size}) for _ in range(3))
    ) == [
        [2 + test_size, 1 + test_size, 3 + test_size, 4 + test_size, 5 + test_size]
        for _ in range(3)
    ]


async def test_invoke_two_processes_two_in_two_out_invalid(
    mocker: MockerFixture,
) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)

    chain_one = Channel.subscribe_to("input") | add_one | Channel.write_to("output")
    chain_two = Channel.subscribe_to("input") | add_one | Channel.write_to("output")

    app = Pregel(chains={"chain_one": chain_one, "chain_two": chain_two})

    with pytest.raises(InvalidUpdateError):
        # LastValue channels can only be updated once per iteration
        await app.ainvoke(2)


async def test_invoke_two_processes_two_in_two_out_valid(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)

    chain_one = Channel.subscribe_to("input") | add_one | Channel.write_to("output")
    chain_two = Channel.subscribe_to("input") | add_one | Channel.write_to("output")

    app = Pregel(
        chains={"chain_one": chain_one, "chain_two": chain_two},
        channels={"output": Topic(int)},
    )

    # An Topic channel accumulates updates into a sequence
    assert await app.ainvoke(2) == [3, 3]


async def test_invoke_checkpoint(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x["total"] + x["input"])

    def raise_if_above_10(input: int) -> int:
        if input > 10:
            raise ValueError("Input is too large")
        return input

    chain_one = (
        Channel.subscribe_to(["input"]).join(["total"])
        | add_one
        | Channel.write_to("output", "total")
        | raise_if_above_10
    )

    app = Pregel(
        chains={"chain_one": chain_one},
        channels={"total": BinaryOperatorAggregate(int, operator.add)},
        checkpoint=MemoryCheckpoint(),
    )

    # total starts out as 0, so output is 0+2=2
    assert await app.ainvoke(2, {"configurable": {"thread_id": "1"}}) == 2
    assert (await app.checkpoint.aget({"configurable": {"thread_id": "1"}})).get(
        "total"
    ) == 2
    # total is now 2, so output is 2+3=5
    assert await app.ainvoke(3, {"configurable": {"thread_id": "1"}}) == 5
    assert (await app.checkpoint.aget({"configurable": {"thread_id": "1"}})).get(
        "total"
    ) == 7
    # total is now 2+5=7, so output would be 7+4=11, but raises ValueError
    with pytest.raises(ValueError):
        await app.ainvoke(4, {"configurable": {"thread_id": "1"}})
    # checkpoint is not updated
    assert (await app.checkpoint.aget({"configurable": {"thread_id": "1"}})).get(
        "total"
    ) == 7
    # on a new thread, total starts out as 0, so output is 0+5=5
    assert await app.ainvoke(5, {"configurable": {"thread_id": "2"}}) == 5
    assert (await app.checkpoint.aget({"configurable": {"thread_id": "1"}})).get(
        "total"
    ) == 7
    assert (await app.checkpoint.aget({"configurable": {"thread_id": "2"}})).get(
        "total"
    ) == 5


async def test_invoke_two_processes_two_in_join_two_out(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    add_10_each = mocker.Mock(side_effect=lambda x: sorted(y + 10 for y in x))

    chain_one = Channel.subscribe_to("input") | add_one | Channel.write_to("inbox")
    chain_three = Channel.subscribe_to("input") | add_one | Channel.write_to("inbox")
    chain_four = (
        Channel.subscribe_to("inbox") | add_10_each | Channel.write_to("output")
    )

    app = Pregel(
        chains={
            "chain_one": chain_one,
            "chain_three": chain_three,
            "chain_four": chain_four,
        },
        channels={"inbox": Topic(int)},
    )

    # Then invoke app
    # We get a single array result as chain_four waits for all publishers to finish
    # before operating on all elements published to topic_two as an array
    for _ in range(100):
        assert await app.ainvoke(2) == [13, 13]

    assert await asyncio.gather(*(app.ainvoke(2) for _ in range(100))) == [
        [13, 13] for _ in range(100)
    ]


async def test_invoke_join_then_call_other_pubsub(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    add_10_each = mocker.Mock(side_effect=lambda x: [y + 10 for y in x])

    inner_app = Pregel(
        chains={
            "one": Channel.subscribe_to("input") | add_one | Channel.write_to("output")
        }
    )

    chain_one = (
        Channel.subscribe_to("input")
        | add_10_each
        | Channel.write_to("inbox_one").map()
    )
    chain_two = (
        Channel.subscribe_to("inbox_one")
        | inner_app.map()
        | sorted
        | Channel.write_to("outbox_one")
    )
    chain_three = Channel.subscribe_to("outbox_one") | sum | Channel.write_to("output")

    app = Pregel(
        chains={
            "chain_one": chain_one,
            "chain_two": chain_two,
            "chain_three": chain_three,
        },
        channels={
            "inbox_one": Topic(int),
            "outbox_one": LastValue(int),
        },
    )

    # Then invoke pubsub
    for _ in range(10):
        assert await app.ainvoke([2, 3]) == 27

    assert await asyncio.gather(*(app.ainvoke([2, 3]) for _ in range(10))) == [
        27 for _ in range(10)
    ]


async def test_invoke_two_processes_one_in_two_out(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)

    chain_one = (
        Channel.subscribe_to("input")
        | add_one
        | Channel.write_to(output=RunnablePassthrough(), between=RunnablePassthrough())
    )
    chain_two = Channel.subscribe_to("between") | add_one | Channel.write_to("output")

    app = Pregel(chains={"chain_one": chain_one, "chain_two": chain_two})

    # Then invoke pubsub
    assert [c async for c in app.astream(2)] == [3, 4]


async def test_invoke_two_processes_no_out(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain_one = Channel.subscribe_to("input") | add_one | Channel.write_to("between")
    chain_two = Channel.subscribe_to("between") | add_one

    app = Pregel(chains={"chain_one": chain_one, "chain_two": chain_two})

    # It finishes executing (once no more messages being published)
    # but returns nothing, as nothing was published to "output" topic
    assert await app.ainvoke(2) is None


async def test_channel_enter_exit_timing(mocker: MockerFixture) -> None:
    setup_sync = mocker.Mock()
    cleanup_sync = mocker.Mock()
    setup_async = mocker.Mock()
    cleanup_async = mocker.Mock()

    @contextmanager
    def an_int() -> Generator[int, None, None]:
        setup_sync()
        try:
            yield 5
        finally:
            cleanup_sync()

    @asynccontextmanager
    async def an_int_async() -> AsyncGenerator[int, None]:
        setup_async()
        try:
            yield 5
        finally:
            cleanup_async()

    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain_one = Channel.subscribe_to("input") | add_one | Channel.write_to("inbox")
    chain_two = (
        Channel.subscribe_to_each("inbox") | add_one | Channel.write_to("output")
    )

    app = Pregel(
        chains={"chain_one": chain_one, "chain_two": chain_two},
        channels={
            "inbox": Topic(int),
            "ctx": Context(an_int, an_int_async, typ=int),
        },
        output=["inbox", "output"],
    )

    async def aenumerate(aiter: AsyncIterator[Any]) -> AsyncIterator[tuple[int, Any]]:
        i = 0
        async for chunk in aiter:
            yield i, chunk
            i += 1

    assert setup_sync.call_count == 0
    assert cleanup_sync.call_count == 0
    assert setup_async.call_count == 0
    assert cleanup_async.call_count == 0
    async for i, chunk in aenumerate(app.astream(2)):
        assert setup_sync.call_count == 0, "Sync context manager should not be used"
        assert cleanup_sync.call_count == 0, "Sync context manager should not be used"
        assert setup_async.call_count == 1, "Expected setup to be called once"
        assert cleanup_async.call_count == 0, "Expected cleanup to not be called yet"
        if i == 0:
            assert chunk == {"inbox": [3]}
        elif i == 1:
            assert chunk == {"output": 4}
        else:
            assert False, "Expected only two chunks"
    assert setup_sync.call_count == 0
    assert cleanup_sync.call_count == 0
    assert setup_async.call_count == 1, "Expected setup to be called once"
    assert cleanup_async.call_count == 1, "Expected cleanup to be called once"
