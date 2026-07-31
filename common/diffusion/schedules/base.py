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

"""Abstract base class for diffusion noise schedules.

**Algorithm Principle:**

A diffusion schedule defines how noise is added to data over time. The core
formulation is a linear interpolation between clean data (x_0) and pure noise
(x_T, typically standard Gaussian):

    x_t = A(t) * x_0 + B(t) * x_T,  t ∈ [0, T]

where:
- x_0 is the clean data sample (signal)
- x_T is pure Gaussian noise (noise)
- A(t) is the signal coefficient (starts at 1 when t=0, decays to 0 when t=T)
- B(t) is the noise coefficient (starts at 0 when t=0, grows to 1 when t=T)

This unified formulation encompasses:
1. **DDPM cosine/linear schedules**: A(t) = sqrt(alpha_bar_t), B(t) = sqrt(1 - alpha_bar_t)
2. **Rectified Flow / Flow Matching**: A(t) = 1 - t/T, B(t) = t/T (linear interpolation)

The schedule also defines conversions between different prediction types
(x_0, x_T, v_cos, v_lerp) and computes derived quantities like SNR.

**Continuous vs Discrete:**
- Continuous schedules (T is float, e.g., T=1.0): Used for flow matching where
  t is a real number in [0, T].
- Discrete schedules (T is int, e.g., T=1000): Used for DDPM-style diffusion
  where t is an integer timestep index.
"""

from abc import ABC, abstractmethod, abstractproperty
from typing import Tuple, Union
import torch

from ..types import PredictionType
from ..utils import expand_dims


class Schedule(ABC):
    """Abstract base class for diffusion interpolation schedules.

    A schedule defines the linear interpolation between data x_0 and noise x_T
    parametrized by time t: x_t = A(t)*x_0 + B(t)*x_T. Subclasses implement
    the coefficient functions A(t) and B(t) for specific schedule types.

    The schedule also provides methods for:
    - Forward noising: computing x_t from x_0 and x_T
    - Prediction conversion: converting between prediction types (x_0, x_T, velocity)
    - SNR computation: signal-to-noise ratio and its inverse
    """

    @abstractproperty
    def T(self) -> Union[int, float]:
        """Maximum timestep (inclusive) of the schedule.

        Returns:
            int for discrete schedules (e.g., 1000), float for continuous
            schedules (e.g., 1.0).
        """

    @abstractmethod
    def A(self, t: torch.Tensor) -> torch.Tensor:
        """Signal interpolation coefficient at timestep t.

        A(t) is the coefficient for x_0 in the interpolation formula:
        x_t = A(t)*x_0 + B(t)*x_T. A(0) = 1 (pure signal) and A(T) = 0
        (pure noise).

        Args:
            t: Timestep tensor of arbitrary shape.

        Returns:
            Coefficient tensor with the same shape as t.
        """

    @abstractmethod
    def B(self, t: torch.Tensor) -> torch.Tensor:
        """Noise interpolation coefficient at timestep t.

        B(t) is the coefficient for x_T in the interpolation formula:
        x_t = A(t)*x_0 + B(t)*x_T. B(0) = 0 (pure signal) and B(T) = 1
        (pure noise).

        Args:
            t: Timestep tensor of arbitrary shape.

        Returns:
            Coefficient tensor with the same shape as t.
        """

    def snr(self, t: torch.Tensor) -> torch.Tensor:
        """Compute the signal-to-noise ratio (SNR) at timestep t.

        SNR is defined as the ratio of signal power to noise power:

            SNR(t) = A(t)^2 / B(t)^2

        SNR is infinite at t=0 (pure signal) and zero at t=T (pure noise).

        Args:
            t: Timestep tensor.

        Returns:
            SNR tensor with the same shape as t.
        """
        return (self.A(t) ** 2) / (self.B(t) ** 2)

    def isnr(self, snr: torch.Tensor) -> torch.Tensor:
        """Compute timestep t from a given SNR value (inverse SNR).

        This is the inverse of :meth:`snr`: given a desired SNR, returns
        the timestep that produces it. Subclasses must implement this for
        their specific A(t), B(t) parameterization.

        Args:
            snr: Signal-to-noise ratio tensor.

        Returns:
            Timestep tensor corresponding to the given SNR.

        Raises:
            NotImplementedError: If not implemented by subclass.
        """
        raise NotImplementedError

    def is_continuous(self) -> bool:
        """Check whether this schedule uses continuous (float) timesteps.

        Returns:
            True if T is a float (continuous schedule), False if T is an int
            (discrete schedule).
        """
        return isinstance(self.T, float)

    def forward(self, x_0: torch.Tensor, x_T: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        """Compute the noisy latent x_t by interpolating x_0 and x_T at timestep t.

        Applies the forward noising formula: x_t = A(t)*x_0 + B(t)*x_T.
        Coefficients A(t) and B(t) are automatically broadcast to match
        the input tensor dimensions.

        Args:
            x_0: Clean data tensor (signal). Shape [B, C, ...].
            x_T: Noise tensor (typically standard Gaussian). Same shape as x_0.
            t: Timestep tensor, shape [B] (one per batch element).

        Returns:
            Noisy latent x_t, same shape as x_0.
        """
        t = expand_dims(t, x_0.ndim)
        return self.A(t) * x_0 + self.B(t) * x_T

    def convert_from_pred(
        self, pred: torch.Tensor, pred_type: PredictionType, x_t: torch.Tensor, t: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Convert a model prediction to predicted x_0 and x_T.

        Given the model's output in the specified prediction type and the
        current noisy state x_t, solves for the implied x_0 and x_T using
        the schedule interpolation formula.

        Conversion formulas:
        - x_T prediction: x_0 = (x_t - B(t)*pred) / A(t), x_T = pred
        - x_0 prediction: x_0 = pred, x_T = (x_t - A(t)*pred) / B(t)
        - v_cos (cosine velocity): x_0 = A(t)*x_t - B(t)*pred, x_T = B(t)*x_t + A(t)*pred
        - v_lerp (rectified flow velocity): x_0 = (x_t - B(t)*pred)/(A(t)+B(t)), x_T = (x_t + A(t)*pred)/(A(t)+B(t))

        Args:
            pred: Model prediction tensor. Same shape as x_t.
            pred_type: What the model predicts (x_0, x_T, v_cos, v_lerp).
            x_t: Current noisy latent at timestep t. Shape [B, C, ...].
            t: Current timestep, shape [B].

        Returns:
            Tuple of (pred_x_0, pred_x_T), both same shape as x_t.

        Raises:
            NotImplementedError: If pred_type is not recognized.
        """
        t = expand_dims(t, x_t.ndim)
        A_t = self.A(t)
        B_t = self.B(t)

        if pred_type == PredictionType.x_T:
            pred_x_T = pred
            pred_x_0 = (x_t - B_t * pred_x_T) / A_t
        elif pred_type == PredictionType.x_0:
            pred_x_0 = pred
            pred_x_T = (x_t - A_t * pred_x_0) / B_t
        elif pred_type == PredictionType.v_cos:
            pred_x_0 = A_t * x_t - B_t * pred
            pred_x_T = A_t * pred + B_t * x_t
        elif pred_type == PredictionType.v_lerp:
            pred_x_0 = (x_t - B_t * pred) / (A_t + B_t)
            pred_x_T = (x_t + A_t * pred) / (A_t + B_t)
        else:
            raise NotImplementedError

        return pred_x_0, pred_x_T

    def convert_to_pred(
        self, x_0: torch.Tensor, x_T: torch.Tensor, t: torch.Tensor, pred_type: PredictionType
    ) -> torch.FloatTensor:
        """Compute the training target for a given prediction type from x_0 and x_T.

        This is the inverse of :meth:`convert_from_pred`: given ground truth
        x_0 and x_T (from training data and sampled noise), computes what the
        model should predict.

        Args:
            x_0: Clean data tensor.
            x_T: Noise tensor.
            t: Timestep tensor.
            pred_type: Which prediction target to compute.

        Returns:
            Prediction target tensor.

        Raises:
            NotImplementedError: If pred_type is not recognized.
        """
        if pred_type == PredictionType.x_T:
            return x_T
        if pred_type == PredictionType.x_0:
            return x_0
        if pred_type == PredictionType.v_cos:
            t = expand_dims(t, x_0.ndim)
            return self.A(t) * x_T - self.B(t) * x_0
        if pred_type == PredictionType.v_lerp:
            return x_T - x_0
        raise NotImplementedError
