import os
if os.getenv('FLAGS_cinn_new_group_scheduler') is None:
    os.environ['FLAGS_cinn_new_group_scheduler'] = '1'
if os.getenv('FLAGS_group_schedule_tiling_first') is None:
    os.environ['FLAGS_group_schedule_tiling_first'] = '1'
if os.getenv('FLAGS_prim_all') is None:
    os.environ['FLAGS_prim_all'] = 'true'
if os.getenv('FLAGS_prim_enable_dynamic') is None:
    os.environ['FLAGS_prim_enable_dynamic'] = '1'
if os.getenv('FLAGS_enable_pir_api') is None:
    os.environ['FLAGS_enable_pir_api'] = '1'
if os.getenv('FLAGS_cinn_bucket_compile') is None:
    os.environ['FLAGS_cinn_bucket_compile'] = '1'

import unittest
import numpy as np
import paddle

def GetEnvVarEnableJit():
    enable_jit = os.getenv('PADDLE_DEBUG_ENABLE_JIT')
    return enable_jit not in {
        "0",
        "False",
        "false",
        "OFF",
    }

def GetEnvVarEnableCinn():
    enable_cinn = os.getenv('PADDLE_DEBUG_ENABLE_CINN')
    if enable_cinn is None:
        return False
    return enable_cinn not in {
        "0",
        "False",
        "false",
        "OFF",
    }


def GetTolerance(dtype):
    if dtype == np.float16:
        return GetFloat16Tolerance()
    if dtype == np.float32:
        return GetFloat32Tolerance()
    return 1e-6

def GetFloat16Tolerance():
    try:
        return float(os.getenv('PADDLE_DEBUG_FLOAT16_TOL'))
    except:
        return 1e-3

def GetFloat32Tolerance():
    try:
        return float(os.getenv('PADDLE_DEBUG_FLOAT32_TOL'))
    except:
        return 1e-6

def IsInteger(dtype):
    return np.dtype(dtype).char in np.typecodes['AllInteger']

def ApplyToStatic(net, use_cinn):
    build_strategy = paddle.static.BuildStrategy()
    build_strategy.build_cinn_pass = use_cinn
    return paddle.jit.to_static(
        net,
        input_spec=net.get_input_spec(),
        build_strategy=build_strategy,
        full_graph=True,
    )

class InstanceTrait:

    @classmethod
    def instance(cls):
        if cls.instance_ is None:
            cls.instance_ = cls()
        return cls.instance_

    @classmethod
    def static_instance_with_cinn(cls):
        if cls.static_instance_with_cinn_ is None:
            cls.static_instance_with_cinn_ = ApplyToStatic(
                cls.instance(),
                use_cinn=True
            )
        return cls.static_instance_with_cinn_

    @classmethod
    def static_instance_without_cinn(cls):
        if cls.static_instance_without_cinn_ is None:
            cls.static_instance_without_cinn_ = ApplyToStatic(
                cls.instance(),
                use_cinn=False
            )
        return cls.static_instance_without_cinn_


class CinnTestBase:

    def setUp(self):
        paddle.seed(2024)
        self.prepare_data()

    def test_train(self):
        dy_outs = self.train(use_cinn=False)
        cinn_outs = self.train(use_cinn=GetEnvVarEnableCinn())

        for cinn_out, dy_out in zip(cinn_outs, dy_outs):
          if type(cinn_out) is list and type(dy_out) is list:
            for x, y in zip(cinn_out, dy_out):
              self.assert_all_close(x, y)
          else:
            self.assert_all_close(cinn_out, dy_out)

    def train(self, use_cinn):
        if GetEnvVarEnableJit():
            net = self.prepare_static_net(use_cinn)
        else:
            net = self.prepare_net()
        out = net(*self.inputs)
        return out
    
    def prepare_data(self):
        self.inputs = self.get_inputs()
        for input in self.inputs:
            input.stop_gradient = True

    def prepare_net(self):
        return self.get_test_class().instance()

    def prepare_static_net(self, use_cinn):
        if use_cinn:
            return self.get_test_class().static_instance_with_cinn()
        else:
            return self.get_test_class().static_instance_without_cinn()

    def assert_all_close(self, x, y):
        if (hasattr(x, "numpy") and hasattr(y, "numpy")):
            x_numpy = x.numpy()
            y_numpy = y.numpy()
            assert x_numpy.dtype == y_numpy.dtype
            if IsInteger(x_numpy.dtype):
                np.testing.assert_equal(x_numpy, y_numpy)
            else:
                tol = GetTolerance(x_numpy.dtype)
                np.testing.assert_allclose(x_numpy, y_numpy, atol=tol, rtol=tol)
        else:
            assert x == y



class PrimitiveOp_1b8631bbd7cfe7b7b038307831649059(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, input_0):
        return paddle._C_ops.mean_all(input_0)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


class TestPrimitiveOp_d64a6fb862531e6b3e68030e75b18330(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1b8631bbd7cfe7b7b038307831649059
    def get_inputs(self):
        return [
            paddle.uniform([4, 28, 28], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_e30df4a4d2a66d9050e94b196b2b8b69(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1b8631bbd7cfe7b7b038307831649059
    def get_inputs(self):
        return [
            paddle.uniform([3, 28, 28], dtype='float32', min=0, max=0.5),
        ]


class PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, input_0):
        return paddle._C_ops.mean_all(input_0)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


class TestPrimitiveOp_eef3265e482f4f2ee612cf9cedc9d54e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([1762, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_d5816a0b08fbd67166f5ef265e5e8841(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([5522, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_ea69a52fe2dc55a30996232b95be55a7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([1760, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_b072bffef53663302302badbfc6b8fea(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([1522, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_5ea5d89ab37fb3a49ed029d1505edfb3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([2074, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_68a2f9ad9bb896ae47a8cec4abd59dd1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([4734, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_2979ace18dce78f597f0821ee3b564e9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1b8631bbd7cfe7b7b038307831649059
    def get_inputs(self):
        return [
            paddle.uniform([6, 28, 28], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_70f992ccc049d1b1235297e13cbc9902(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([1074, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_3b416c45c9278edada54a60a5cb9b39d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([2332, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_40ead7a1546ecb946640c90046503a86(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([3051, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_c65273d3ae3ffee140c17befed4c5894(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([3870, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_0787bdd90f3ca557d9a98ade1bae7325(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1b8631bbd7cfe7b7b038307831649059
    def get_inputs(self):
        return [
            paddle.uniform([2, 28, 28], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_32c0543d4707cff86b640404bbabbfd4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([2111, 4], dtype='float32', min=0, max=0.5),
        ]


class TestPrimitiveOp_84658bef51dd7d800485190da1c4fbef(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19ad044ac92760cbe91bfedecfd6d51b
    def get_inputs(self):
        return [
            paddle.uniform([4141, 4], dtype='float32', min=0, max=0.5),
        ]




if __name__ == '__main__':
    unittest.main()