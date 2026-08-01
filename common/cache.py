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

"""Key-value caching utility for memoizing expensive computation results.

This module provides a simple but flexible caching mechanism used during
model inference to avoid redundant computation. It supports:
- Lazy evaluation via callable thunks
- Namespaced cache keys to prevent collisions
- Cache disablement for debugging
- Shared underlying storage across namespace views

Typical use case: During diffusion sampling, certain precomputed values
(e.g., positional embedding shapes, padding sizes) are the same across
denoising steps and can be cached after first computation.
"""

from collections.abc import Callable


class Cache:
    """Lazy key-value cache for reusable computation results.

    The cache uses a lazy evaluation pattern: instead of precomputing values,
    the caller passes a key and a zero-argument callable (thunk) that computes
    the value on first access. Subsequent calls with the same key return the
    cached result without invoking the thunk.

    The cache supports namespacing via :meth:`namespace`, which creates a new
    Cache view that shares the same underlying dict but prepends a namespace
    prefix to all keys. This is useful for organizing cache entries by
    component or stage.

    Args:
        disable: If True, caching is disabled and thunks are called every time.
            Useful for debugging. Defaults to False.
        prefix: Key prefix for this cache view, used for namespacing.
            Defaults to empty string.
        cache: Optional pre-existing dict to use as backing storage. If None,
            a new empty dict is created. Defaults to None.

    Example:
        >>> cache = Cache()
        >>> # First call computes the value
        >>> x = cache("key1", lambda: expensive_computation())
        >>> # Second call returns cached result
        >>> x = cache("key1", lambda: expensive_computation())  # thunk not called
        >>>
        >>> # Create a namespaced sub-cache
        >>> attn_cache = cache.namespace("attn")
        >>> attn_cache("q_shape", lambda: (B, H, T, D))  # key = "attn.q_shape"
    """

    def __init__(self, disable=False, prefix="", cache=None):
        self.cache = cache if cache is not None else {}
        self.disable = disable
        self.prefix = prefix

    def __call__(self, key: str, fn: Callable):
        """Retrieve a cached value, computing it if necessary.

        Looks up ``key`` (with prefix prepended) in the cache. If found, returns
        the cached value. If not found (or cache is disabled), calls ``fn()`` to
        compute the value, stores it, and returns it.

        Args:
            key: The cache key (without prefix).
            fn: A zero-argument callable that computes the value on cache miss.

        Returns:
            The cached or newly computed value.
        """
        if self.disable:
            return fn()

        key = self.prefix + key
        try:
            result = self.cache[key]
        except KeyError:
            result = fn()
            self.cache[key] = result
        return result

    def namespace(self, namespace: str):
        """Create a namespaced view of this cache sharing the same storage.

        The returned Cache object uses the same underlying dict but prepends
        ``<namespace>.`` to all keys (on top of any existing prefix). This
        allows creating hierarchical cache scopes without copying data.

        Args:
            namespace: The namespace string to prepend.

        Returns:
            A new Cache instance sharing the same backing dict with an
            extended key prefix.

        Example:
            >>> cache = Cache()
            >>> attn = cache.namespace("attn")
            >>> mlp = cache.namespace("mlp")
            >>> attn("x", fn)   # key = "attn.x"
            >>> mlp("x", fn)    # key = "mlp.x"  (no collision)
        """
        return Cache(
            disable=self.disable,
            prefix=self.prefix + namespace + ".",
            cache=self.cache,
        )

    def get(self, key: str):
        """Directly retrieve a cached value without computing.

        Unlike ``__call__``, this method does not accept a thunk and raises
        KeyError if the key is not found. Useful for asserting that a value
        has already been cached.

        Args:
            key: The cache key (without prefix).

        Returns:
            The cached value.

        Raises:
            KeyError: If the key is not present in the cache.
        """
        key = self.prefix + key
        return self.cache[key]
