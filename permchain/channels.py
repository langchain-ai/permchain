import json
from abc import ABC, abstractmethod
from typing import Callable, FrozenSet, Generic, Optional, Sequence, TypeVar

from typing_extensions import Self, get_args

Value = TypeVar("Value")
Update = TypeVar("Update")


class EmptyChannelError(Exception):
    pass


class InvalidUpdateError(Exception):
    pass


class Channel(Generic[Value, Update], ABC):
    # TODO: add type hints for ValueType and UpdateType
    # @property
    # def ValueType(self) -> type[Value]:
    #     """The type of the value stored in the channel."""
    #     type_args = get_args(self.__class__.__orig_bases__[-1])  # type: ignore[attr-defined]
    #     if type_args and len(type_args) == 2:
    #         return type_args[0]

    # @property
    # def UpdateType(self) -> type[Update]:
    #     """The type of the update received by the channel."""
    #     type_args = get_args(self.__class__.__orig_bases__[-1])  # type: ignore[attr-defined]
    #     if type_args and len(type_args) == 2:
    #         return type_args[1]

    @abstractmethod
    def _empty(self, checkpoint: Optional[str] = None) -> Self:
        ...

    @abstractmethod
    def _update(self, values: Sequence[Update]) -> None:
        ...

    @abstractmethod
    def _get(self) -> Value:
        ...

    @abstractmethod
    def _checkpoint(self) -> str:
        ...


class BinaryOperatorAggregate(Generic[Value], Channel[Value, Value]):
    """Stores the result of applying a binary operator to the current value and each new value.

    ```python
    import operator

    total = BinaryOperatorAggregate[int]("total", operator.add)
    ```
    """

    def __init__(self, operator: Callable[[Value, Value], Value]):
        super().__init__()
        self.operator = operator

    def _empty(self, checkpoint: Optional[str] = None) -> Self:
        empty = self.__class__(self.operator)
        if checkpoint is not None:
            empty.value = json.loads(checkpoint)
        return empty

    def _update(self, values: Sequence[Value]) -> None:
        if not hasattr(self, "value"):
            self.value = values[0]
            values = values[1:]

        for value in values:
            self.value = self.operator(self.value, value)

    def _get(self) -> Value:
        try:
            return self.value
        except AttributeError:
            raise EmptyChannelError()

    def _checkpoint(self) -> str:
        return json.dumps(self.value)


class LastValue(Generic[Value], Channel[Value, Value]):
    """Stores the last value received."""

    def _empty(self, checkpoint: Optional[str] = None) -> Self:
        empty = self.__class__()
        if checkpoint is not None:
            empty.value = json.loads(checkpoint)
        return empty

    def _update(self, values: Sequence[Value]) -> None:
        if len(values) != 1:
            raise InvalidUpdateError()

        self.value = values[-1]

    def _get(self) -> Value:
        try:
            return self.value
        except AttributeError:
            raise EmptyChannelError()

    def _checkpoint(self) -> str:
        return json.dumps(self.value)


class Inbox(Generic[Value], Channel[Sequence[Value], Value]):
    """Stores all values received, resets in each step."""

    def _empty(self, checkpoint: Optional[str] = None) -> Self:
        empty = self.__class__()
        if checkpoint is not None:
            empty.queue = tuple(json.loads(checkpoint))
        return empty

    def _update(self, values: Sequence[Value]) -> None:
        self.queue = tuple(values)

    def _get(self) -> Sequence[Value]:
        try:
            return self.queue
        except AttributeError:
            raise EmptyChannelError()

    def _checkpoint(self) -> str:
        return json.dumps(self.queue)


class Set(Generic[Value], Channel[FrozenSet[Value], Value]):
    """Stores all unique values received."""

    set: set[Value]

    def _empty(self, checkpoint: Optional[str] = None) -> Self:
        empty = self.__class__()
        if checkpoint is not None:
            empty.set = set(json.loads(checkpoint))
        return empty

    def _update(self, values: Sequence[Value]) -> None:
        if not hasattr(self, "set"):
            self.set = set()
        self.set.update(values)

    def _get(self) -> FrozenSet[Value]:
        try:
            return frozenset(self.set)
        except AttributeError:
            raise EmptyChannelError()

    def _checkpoint(self) -> str:
        return json.dumps(list(self.set))