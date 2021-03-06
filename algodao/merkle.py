from __future__ import annotations

import math
import hashlib
from typing import Dict, List, Optional


class Node:
    @classmethod
    def from_nodes(cls, left: Node, right: Node) -> Node:
        value: bytes = cls.hash(left.value + right.value)
        return Node(left, right, value)

    @classmethod
    def from_value(cls, value: bytes) -> Node:
        return Node(None, None, cls.hash(value))

    @classmethod
    def hash(cls, value: bytes) -> bytes:
        return hashlib.sha256(value).digest()

    def __init__(self, left: Optional[Node], right: Optional[Node], value: bytes):
        self._left: Optional[Node] = left
        self._right: Optional[Node] = right
        self._value = value

    @property
    def value(self) -> bytes:
        return self._value

    @property
    def left(self) -> Optional[Node]:
        return self._left

    @property
    def right(self) -> Optional[Node]:
        return self._right


class MerkleTree:
    def __init__(self, values: List[bytes]):
        leaves: List[Node] = [Node.from_value(val) for val in values]
        # pad to 2**n for simplicity in implementation
        self._depth = int(math.ceil(math.log(len(leaves))))
        numleaves = 2**self._depth
        # special case for len(leaves) == 1
        if numleaves == 1:
            numleaves = 2
            self._depth = 1
        zeronode = Node.from_value(bytes(0))
        self._leaves = leaves + [zeronode] * (numleaves - len(leaves))
        self._root: Node = self._buildtree(self._leaves)
        self._levels: Dict[int, List[Node]] = self._createlevels()

    @property
    def roothash(self) -> bytes:
        return self._root.value

    @classmethod
    def _buildtree(self, leaves: List[Node]) -> Node:
        assert len(leaves) % 2 == 0
        assert len(leaves) != 0
        if len(leaves) == 2:
            return Node.from_nodes(leaves[0], leaves[1])
        half: int = len(leaves) // 2
        if half % 2 == 0:
            half += 1
        left: Node = self._buildtree(leaves[::2])
        right: Node = self._buildtree(leaves[1::2])
        return Node.from_nodes(left, right)

    def _createlevels(self) -> Dict[int, List[Node]]:
        levels: Dict[int, List[Node]] = dict()
        self._appendtolevel(levels, self._root, 0)
        return levels

    @classmethod
    def _appendtolevel(
            cls,
            levels: Dict[int, List[Node]],
            node: Node,
            depth: int
    ):
        assert node is not None
        existing: List[Node] = levels.setdefault(depth, [])
        existing.append(node)
        if node.left is not None:
            assert node.right is not None
            cls._appendtolevel(levels, node.left, depth+1)
            cls._appendtolevel(levels, node.right, depth+1)

    def createproof(self, index) -> List[bytes]:
        hashes: List[bytes] = list()
        depth = self._depth
        assert depth > 0
        while depth != 0:
            if index % 2 == 0:
                left = self._levels[depth][index]
                right = self._levels[depth][index+1]
                hashes.append(right.value)
            else:
                left = self._levels[depth][index-1]
                right = self._levels[depth][index]
                hashes.append(left.value)
            index = index // 2
            depth -= 1
        assert index in (0, 1)
        assert(Node.hash(left.value + right.value) == self._root.value)
        return hashes
