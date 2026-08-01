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

"""Configuration utility functions for loading and managing YAML configs.

This module provides utilities for:
- Loading YAML configuration files using OmegaConf
- Resolving config inheritance via ``__inherit__`` directive
- Merging command-line arguments into configs
- Dynamically importing and instantiating Python objects from config specs
- Recursive config resolution

The config system supports hierarchical inheritance where child configs can
extend parent configs, with child values overriding parent values.
"""

import importlib
from collections.abc import Callable
from typing import Any

from omegaconf import DictConfig, ListConfig, OmegaConf

OmegaConf.register_new_resolver("eval", eval)


def load_config(path: str, argv: list[str] = None) -> DictConfig | ListConfig:
    """Load a configuration file and resolve inheritance hierarchies.

    Loads a YAML config from the specified path, optionally merges command-line
    dotlist arguments, then recursively resolves all ``__inherit__`` directives
    to build the complete merged configuration.

    Args:
        path: Filesystem path to the YAML configuration file.
        argv: Optional list of command-line arguments in dotlist format
            (e.g., ``["model.latent_channels=16", "training.batch_size=8"]``).
            These values override those loaded from the file.

    Returns:
        The fully resolved configuration as a DictConfig or ListConfig.

    Example:
        >>> config = load_config("configs/train.yaml", argv=["training.lr=1e-4"])
    """
    config = OmegaConf.load(path)
    if argv is not None:
        config_argv = OmegaConf.from_dotlist(argv)
        config = OmegaConf.merge(config, config_argv)
    config = resolve_recursive(config, resolve_inheritance)
    return config


def resolve_recursive(
    config: Any,
    resolver: Callable[[DictConfig | ListConfig], DictConfig | ListConfig],
) -> Any:
    """Recursively apply a resolver function to all nested config nodes.

    Traverses the configuration tree depth-first, applying the resolver to
    DictConfig and ListConfig nodes. Nested structures are resolved bottom-up:
    children are resolved before their parents.

    Args:
        config: The configuration node (DictConfig, ListConfig, or scalar).
        resolver: A callable that takes a config node and returns the resolved node.

    Returns:
        The fully resolved configuration with the resolver applied at all levels.
    """
    config = resolver(config)
    if isinstance(config, DictConfig):
        for k in config:
            v = config.get(k)
            if isinstance(v, (DictConfig, ListConfig)):
                config[k] = resolve_recursive(v, resolver)
    if isinstance(config, ListConfig):
        for i in range(len(config)):
            v = config.get(i)
            if isinstance(v, (DictConfig, ListConfig)):
                config[i] = resolve_recursive(v, resolver)
    return config


def resolve_inheritance(config: DictConfig | ListConfig) -> Any:
    """Recursively resolve ``__inherit__`` directives in config dicts.

    When a DictConfig contains an ``__inherit__`` key, the specified parent
    config(s) are loaded and merged. Multiple parents can be specified as a
    list, merged left-to-right (later parents override earlier ones), and the
    current config overrides all parent values.

    The ``__inherit__`` key is removed after resolution.

    Inheritance chain example::

        base.yaml:
            model:
                dim: 256
                depth: 12

        child.yaml:
            __inherit__: base.yaml
            model:
                depth: 24

        Result: model.dim=256, model.depth=24

    Args:
        config: A configuration node. Only DictConfig nodes with ``__inherit__``
            are processed; other nodes are returned unchanged.

    Returns:
        The merged configuration with inheritance resolved, or the original
        config if no inheritance directive is present.
    """
    if isinstance(config, DictConfig):
        inherit = config.pop("__inherit__", None)

        if inherit:
            inherit_list = inherit if isinstance(inherit, ListConfig) else [inherit]

            parent_config = None
            for parent_path in inherit_list:
                assert isinstance(parent_path, str)
                parent_config = (
                    load_config(parent_path)
                    if parent_config is None
                    else OmegaConf.merge(parent_config, load_config(parent_path))
                )

            if len(config.keys()) > 0:
                config = OmegaConf.merge(parent_config, config)
            else:
                config = parent_config
    return config


def import_item(path: str, name: str) -> Any:
    """Dynamically import a Python class, function, or object from a module.

    Args:
        path: Dotted module path (e.g., ``"models.dit_v2"``).
        name: Name of the attribute to retrieve from the module (e.g., ``"DiT"``).

    Returns:
        The imported Python object.

    Example:
        >>> DiTClass = import_item("models.dit_v2", "DiT")
        >>> model = DiTClass(dim=512)
    """
    return getattr(importlib.import_module(path), name)


def create_object(config: DictConfig) -> Any:
    """Instantiate a Python object from a configuration dict.

    The config must contain an ``__object__`` key specifying how to create
    the object:

    - ``__object__.path``: Dotted module path to import from.
    - ``__object__.name``: Name of the class/callable in the module.
    - ``__object__.args``: How to pass config as arguments. Options:
        - ``"as_config"`` (default): Pass the entire DictConfig as a single argument.
        - ``"as_params"``: Convert config to a plain dict and unpack as keyword arguments
          (the ``__object__`` key is removed first).

    Args:
        config: DictConfig containing the ``__object__`` specification.

    Returns:
        The instantiated object.

    Raises:
        NotImplementedError: If ``args`` type is not recognized.

    Example config::

        optimizer:
          __object__:
            path: torch.optim
            name: AdamW
            args: as_params
          lr: 1e-4
          weight_decay: 0.01
    """
    item = import_item(
        path=config.__object__.path,
        name=config.__object__.name,
    )
    args = config.__object__.get("args", "as_config")
    if args == "as_config":
        return item(config)
    if args == "as_params":
        config = OmegaConf.to_object(config)
        config.pop("__object__")
        return item(**config)
    raise NotImplementedError(f"Unknown args type: {args}")
