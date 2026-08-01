# // Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# //
# // Licensed under the Apache License, Version 2.0 (the "License");
# // you may not use this file except in compliance with the License.
# // You may obtain a copy of the License at
# //
# //     http://www.apache.org/licenses/LICENSE-2.0
# //
# // Unless required by applicable law or agreed to in writing, software
# // distributed under the License is distributed on an "AS IS" BASIS,
# // WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# // See the License for the specific language governing permissions and
# // limitations under the License.

"""List partitioning and rotation utility functions.

This module provides simple but frequently used list manipulation utilities:
- Partitioning lists into fixed-size chunks
- Distributing list elements across a fixed number of groups (round-robin)
- Rotating/cyclic-shifting lists

These are commonly used for data parallel workload distribution, batch
splitting, and cyclic task assignment in distributed training.
"""

from typing import Any


def partition_by_size(data: list[Any], size: int) -> list[list[Any]]:
    """Partition a list into consecutive chunks of a fixed maximum size.

    The list is split greedily from left to right. If the total length is
    not evenly divisible by ``size``, the last chunk will contain fewer
    elements.

    Args:
        data: The input list to partition.
        size: Maximum number of elements per chunk. Must be positive.

    Returns:
        A list of sublists, where each sublist (except possibly the last)
        has exactly ``size`` elements.

    Raises:
        AssertionError: If ``size`` is not positive.

    Examples:
        >>> partition_by_size([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]

        >>> partition_by_size([1, 2, 3, 4], 2)
        [[1, 2], [3, 4]]
    """
    assert size > 0
    return [data[i : (i + size)] for i in range(0, len(data), size)]


def partition_by_groups(data: list[Any], groups: int) -> list[list[Any]]:
    """Distribute list elements across a fixed number of groups (round-robin).

    Elements are assigned to groups in a round-robin fashion: the i-th element
    goes to group ``i % groups``. This produces a balanced distribution where
    group sizes differ by at most 1 when the list length is not evenly divisible.

    This is the standard way to split data across data-parallel workers.

    Args:
        data: The input list to distribute.
        groups: Number of groups to create. Must be positive.

    Returns:
        A list of ``groups`` sublists, containing the elements distributed
        round-robin.

    Raises:
        AssertionError: If ``groups`` is not positive.

    Examples:
        >>> partition_by_groups([1, 2, 3, 4, 5], 2)
        [[1, 3, 5], [2, 4]]

        >>> partition_by_groups([1, 2, 3, 4], 2)
        [[1, 3], [2, 4]]
    """
    assert groups > 0
    return [data[i::groups] for i in range(groups)]


def shift_list(data: list[Any], n: int) -> list[Any]:
    """Rotate/cyclically shift a list by n positions to the left.

    The first ``n % len(data)`` elements are moved to the end of the list.
    Equivalent to a left rotation by ``n`` positions.

    Args:
        data: The input list to rotate.
        n: Number of positions to shift. Positive values shift left;
            negative values shift right (equivalent to shifting left by
            ``len(data) + n``).

    Returns:
        A new list with elements rotated.

    Examples:
        >>> shift_list([1, 2, 3, 4, 5], 3)
        [4, 5, 1, 2, 3]

        >>> shift_list([1, 2, 3, 4, 5], -1)
        [5, 1, 2, 3, 4]

        >>> shift_list([1, 2, 3], 0)
        [1, 2, 3]
    """
    return data[(n % len(data)) :] + data[: (n % len(data))]
