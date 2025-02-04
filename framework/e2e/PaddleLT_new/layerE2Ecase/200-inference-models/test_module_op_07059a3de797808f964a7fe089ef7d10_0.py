import os
os.environ['FLAGS_cinn_new_group_scheduler'] = '1'
os.environ['FLAGS_group_schedule_tiling_first'] = '1'
os.environ['FLAGS_enable_pir_api'] = '1'
os.environ['FLAGS_cinn_bucket_compile'] = '1'
import sys
import unittest
import numpy as np
from dataclasses import dataclass
import typing as t

@dataclass
class Stage:
    name: str
    env_vars: t.Dict[str, str]

cinn_stages = [
    Stage(
        name="dynamic_to_static",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=False,
            FLAGS_prim_all=False,
            FLAGS_prim_enable_dynamic=False,
        ),
    ),
    Stage(
        name="prim",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=False,
            FLAGS_prim_all=True,
            FLAGS_prim_enable_dynamic=True,
        ),
    ),
    Stage(
        name="infer_symbolic",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=False,
            FLAGS_prim_all=True,
            FLAGS_prim_enable_dynamic=True,
            FLAGS_use_cinn=False,
            FLAGS_check_infer_symbolic=True,
        ),
    ),
	Stage(
        name="frontend",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=True,
            FLAGS_prim_all=True,
            FLAGS_prim_enable_dynamic=True,
            FLAGS_use_cinn=True,
            FLAGS_check_infer_symbolic=False,
            FLAGS_enable_fusion_fallback=True,
        ), 
    ),
    Stage(
        name="backend",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=True,
            FLAGS_prim_all=True,
            FLAGS_prim_enable_dynamic=True,
            FLAGS_use_cinn=True,
            FLAGS_check_infer_symbolic=False,
            FLAGS_enable_fusion_fallback=False,
        ), 
    ),
]

def GetCinnStageByName(name):
    for stage in cinn_stages:
        if stage.name == name:
            return stage
    return None

def GetCurrentCinnStage():
    name = os.getenv('PADDLE_DEBUG_CINN_STAGE_NAME')
    if name is None:
        return None
    stage_names = [stage.name for stage in cinn_stages]
    assert name in stage_names, (
        f"PADDLE_DEBUG_CINN_STAGE_NAME should be in {stage_names}"
    )
    return GetCinnStageByName(name)

def GetPrevCinnStage(stage):
    for i in range(1, len(cinn_stages)):
        if stage is cinn_stages[i]:
            return cinn_stages[i - 1]
    return None

def IsCinnStageEnableDiff():
    value = os.getenv('PADDLE_DEBUG_CINN_STAGE_ENABLE_DIFF')
    enabled = value in {
        '1',
        'true',
        'True',
    }
    if enabled:
        assert GetCurrentCinnStage() is not None
    return enabled

def GetExitCodeAndStdErr(cmd, env):
    env = {
        k:v
        for k, v in env.items()
        if v is not None
    }
    import subprocess
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    return result.returncode, result.stderr

def GetStageExitCodeAndStdErr(stage):
    return GetExitCodeAndStdErr(
        [sys.executable, __file__],
        env=dict(
            PADDLE_DEBUG_CINN_STAGE_NAME=stage.name,
            PADDLE_DEBUG_CINN_STAGE_ENABLE_DIFF='0',
            PYTHONPATH=os.getenv('PYTHONPATH'),
            ATHENA_ENABLE_TRY_RUN="False",
        ),
    )

def AthenaTryRunEnabled():
    return os.getenv('ATHENA_ENABLE_TRY_RUN') not in {
        "0",
        "False",
        "false",
        "OFF"
    }

def GetNeedSkipAndSkipMessage():
    current_stage = GetCurrentCinnStage()
    assert current_stage is not None
    if not IsCinnStageEnableDiff():
        return False, ""
    last_stage = GetPrevCinnStage(current_stage)
    if last_stage is None:
        return False, ""
    exitcode, stderr = GetStageExitCodeAndStdErr(last_stage)
    if exitcode != 0:
        return True, f"last stage failed."
    return False, ""

def GetCurrentStageTryRunExitCodeAndStdErr():
    if not AthenaTryRunEnabled():
        return False, ""
    current_stage = GetCurrentCinnStage()
    assert current_stage is not None
    return GetStageExitCodeAndStdErr(current_stage)

def SetDefaultEnv(**env_var2value):
    for env_var, value in env_var2value.items():
        if os.getenv(env_var) is None:
            os.environ[env_var] = str(value)

SetDefaultEnv(
    PADDLE_DEBUG_CINN_STAGE_NAME="backend",
    PADDLE_DEBUG_CINN_STAGE_ENABLE_DIFF=False,
    PADDLE_DEBUG_ENABLE_CINN=True,
    FLAGS_enable_pir_api=True,
    FLAGS_prim_all=True,
    FLAGS_prim_enable_dynamic=True,
    FLAGS_use_cinn=False,
    FLAGS_check_infer_symbolic=False,
    FLAGS_enable_fusion_fallback=False,
)

need_skip, skip_message = GetNeedSkipAndSkipMessage()
try_run_exit_code, try_run_stderr = GetCurrentStageTryRunExitCodeAndStdErr()
class TestTryRun(unittest.TestCase):
    def test_panic(self):
        if not AthenaTryRunEnabled():
            return
        if try_run_exit_code == 0:
            # All unittest cases passed.
            return
        if try_run_exit_code > 0:
            # program failed but not panic.
            return
        # program panicked.
        kOutputLimit = 65536
        message = try_run_stderr[-kOutputLimit:]
        raise RuntimeError(f"panicked. last {kOutputLimit} characters of stderr: \n{message}")

import paddle

def SetEnvVar(env_var2value):
    for env_var, value in env_var2value.items():
        os.environ[env_var] = str(value)
    paddle.set_flags({
        env_var:value
        for env_var, value in env_var2value.items()
        if env_var.startswith('FLAGS_')
    })

if GetCurrentCinnStage() is not None:
    SetEnvVar(GetCurrentCinnStage().env_vars)

def NumOperationsInBlock(block_idx):
    return [1259][block_idx] - 1 # number-of-ops-in-block

def GetPaddleDebugNumAllowedOps():
    try:
        return int(os.getenv('PADDLE_DEBUG_NUM_ALLOWED_OPS'))
    except:
        return None

paddle_debug_num_allowed_ops = GetPaddleDebugNumAllowedOps()


if type(paddle_debug_num_allowed_ops) is not int:
    def EarlyReturn(block_idx, op_idx):
        return False      
else:
    def EarlyReturn(block_idx, op_idx):
        return op_idx >= paddle_debug_num_allowed_ops

class BlockEntries:
    def builtin_module_3188_0_0(self, constant_46, constant_45, constant_44, constant_43, constant_42, constant_41, parameter_301, parameter_274, parameter_247, parameter_220, parameter_193, parameter_166, parameter_139, parameter_112, constant_40, parameter_85, parameter_84, constant_39, constant_38, constant_37, constant_36, constant_35, constant_34, constant_33, constant_32, parameter_54, constant_31, parameter_53, constant_30, constant_29, constant_28, constant_27, constant_26, constant_25, constant_24, constant_23, constant_22, constant_21, constant_20, parameter_23, constant_19, parameter_22, constant_18, constant_17, constant_16, constant_15, constant_14, constant_13, constant_12, constant_11, constant_10, constant_9, constant_8, constant_7, constant_6, constant_5, constant_4, constant_3, constant_2, constant_1, constant_0, parameter_1, parameter_0, parameter_3, parameter_2, parameter_5, parameter_4, parameter_6, parameter_7, parameter_8, parameter_9, parameter_10, parameter_12, parameter_11, parameter_13, parameter_14, parameter_15, parameter_16, parameter_18, parameter_17, parameter_19, parameter_20, parameter_21, parameter_24, parameter_25, parameter_27, parameter_26, parameter_28, parameter_29, parameter_30, parameter_31, parameter_33, parameter_32, parameter_34, parameter_36, parameter_35, parameter_37, parameter_38, parameter_39, parameter_40, parameter_41, parameter_43, parameter_42, parameter_44, parameter_45, parameter_46, parameter_47, parameter_49, parameter_48, parameter_50, parameter_51, parameter_52, parameter_55, parameter_56, parameter_58, parameter_57, parameter_59, parameter_60, parameter_61, parameter_62, parameter_64, parameter_63, parameter_65, parameter_67, parameter_66, parameter_68, parameter_69, parameter_70, parameter_71, parameter_72, parameter_74, parameter_73, parameter_75, parameter_76, parameter_77, parameter_78, parameter_80, parameter_79, parameter_81, parameter_82, parameter_83, parameter_86, parameter_87, parameter_89, parameter_88, parameter_90, parameter_91, parameter_92, parameter_93, parameter_95, parameter_94, parameter_96, parameter_97, parameter_98, parameter_99, parameter_100, parameter_102, parameter_101, parameter_103, parameter_104, parameter_105, parameter_106, parameter_108, parameter_107, parameter_109, parameter_110, parameter_111, parameter_113, parameter_114, parameter_116, parameter_115, parameter_117, parameter_118, parameter_119, parameter_120, parameter_122, parameter_121, parameter_123, parameter_124, parameter_125, parameter_126, parameter_127, parameter_129, parameter_128, parameter_130, parameter_131, parameter_132, parameter_133, parameter_135, parameter_134, parameter_136, parameter_137, parameter_138, parameter_140, parameter_141, parameter_143, parameter_142, parameter_144, parameter_145, parameter_146, parameter_147, parameter_149, parameter_148, parameter_150, parameter_151, parameter_152, parameter_153, parameter_154, parameter_156, parameter_155, parameter_157, parameter_158, parameter_159, parameter_160, parameter_162, parameter_161, parameter_163, parameter_164, parameter_165, parameter_167, parameter_168, parameter_170, parameter_169, parameter_171, parameter_172, parameter_173, parameter_174, parameter_176, parameter_175, parameter_177, parameter_178, parameter_179, parameter_180, parameter_181, parameter_183, parameter_182, parameter_184, parameter_185, parameter_186, parameter_187, parameter_189, parameter_188, parameter_190, parameter_191, parameter_192, parameter_194, parameter_195, parameter_197, parameter_196, parameter_198, parameter_199, parameter_200, parameter_201, parameter_203, parameter_202, parameter_204, parameter_205, parameter_206, parameter_207, parameter_208, parameter_210, parameter_209, parameter_211, parameter_212, parameter_213, parameter_214, parameter_216, parameter_215, parameter_217, parameter_218, parameter_219, parameter_221, parameter_222, parameter_224, parameter_223, parameter_225, parameter_226, parameter_227, parameter_228, parameter_230, parameter_229, parameter_231, parameter_232, parameter_233, parameter_234, parameter_235, parameter_237, parameter_236, parameter_238, parameter_239, parameter_240, parameter_241, parameter_243, parameter_242, parameter_244, parameter_245, parameter_246, parameter_248, parameter_249, parameter_251, parameter_250, parameter_252, parameter_253, parameter_254, parameter_255, parameter_257, parameter_256, parameter_258, parameter_259, parameter_260, parameter_261, parameter_262, parameter_264, parameter_263, parameter_265, parameter_266, parameter_267, parameter_268, parameter_270, parameter_269, parameter_271, parameter_272, parameter_273, parameter_275, parameter_276, parameter_278, parameter_277, parameter_279, parameter_280, parameter_281, parameter_282, parameter_284, parameter_283, parameter_285, parameter_286, parameter_287, parameter_288, parameter_289, parameter_291, parameter_290, parameter_292, parameter_293, parameter_294, parameter_295, parameter_297, parameter_296, parameter_298, parameter_299, parameter_300, parameter_302, parameter_303, parameter_305, parameter_304, parameter_306, parameter_307, parameter_308, parameter_309, parameter_311, parameter_310, parameter_312, parameter_314, parameter_313, parameter_315, parameter_316, parameter_317, parameter_318, parameter_319, parameter_321, parameter_320, parameter_322, parameter_323, parameter_324, parameter_325, parameter_327, parameter_326, parameter_328, parameter_329, parameter_330, parameter_331, parameter_332, parameter_334, parameter_333, parameter_335, parameter_336, parameter_337, parameter_338, parameter_340, parameter_339, parameter_341, parameter_342, feed_0):

        # pd_op.cast: (-1x3x384x384xf16) <- (-1x3x384x384xf32)
        cast_0 = paddle._C_ops.cast(feed_0, paddle.float16)

        # pd_op.conv2d: (-1x128x96x96xf16) <- (-1x3x384x384xf16, 128x3x4x4xf16)
        conv2d_0 = paddle._C_ops.conv2d(cast_0, parameter_0, [4, 4], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.add_: (-1x128x96x96xf16) <- (-1x128x96x96xf16, 1x128x1x1xf16)
        add__0 = paddle._C_ops.add_(conv2d_0, parameter_1)

        # pd_op.flatten_: (-1x128x9216xf16, None) <- (-1x128x96x96xf16)
        flatten__0, flatten__1 = (lambda x, f: f(x))(paddle._C_ops.flatten_(add__0, 2, 3), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x9216x128xf16) <- (-1x128x9216xf16)
        transpose_0 = paddle._C_ops.transpose(flatten__0, [0, 2, 1])

        # pd_op.layer_norm: (-1x9216x128xf16, -9216xf32, -9216xf32) <- (-1x9216x128xf16, 128xf32, 128xf32)
        layer_norm_0, layer_norm_1, layer_norm_2 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(transpose_0, parameter_2, parameter_3, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.shape: (3xi32) <- (-1x9216x128xf16)
        shape_0 = paddle._C_ops.shape(paddle.cast(layer_norm_0, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_0 = paddle._C_ops.slice(shape_0, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x9216x128xf16, -9216xf32, -9216xf32) <- (-1x9216x128xf16, 128xf32, 128xf32)
        layer_norm_3, layer_norm_4, layer_norm_5 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(layer_norm_0, parameter_4, parameter_5, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_0 = [slice_0, constant_2, constant_2, constant_3]

        # pd_op.reshape_: (-1x96x96x128xf16, 0x-1x9216x128xf16) <- (-1x9216x128xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__0, reshape__1 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_3, combine_0), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x96x96x128xf16)
        shape_1 = paddle._C_ops.shape(paddle.cast(reshape__0, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_1 = paddle._C_ops.slice(shape_1, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_1 = [slice_1, constant_4, constant_5, constant_4, constant_5, constant_3]

        # pd_op.reshape_: (-1x8x12x8x12x128xf16, 0x-1x96x96x128xf16) <- (-1x96x96x128xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__2, reshape__3 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__0, combine_1), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x8x8x12x12x128xf16) <- (-1x8x12x8x12x128xf16)
        transpose_1 = paddle._C_ops.transpose(reshape__2, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x128xf16, 0x-1x8x8x12x12x128xf16) <- (-1x8x8x12x12x128xf16, 4xi64)
        reshape__4, reshape__5 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_1, constant_6), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x128xf16, 0x-1x12x12x128xf16) <- (-1x12x12x128xf16, 3xi64)
        reshape__6, reshape__7 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__4, constant_7), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x128xf16)
        shape_2 = paddle._C_ops.shape(paddle.cast(reshape__6, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_2 = paddle._C_ops.slice(shape_2, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x384xf16) <- (-1x144x128xf16, 128x384xf16)
        matmul_0 = paddle.matmul(reshape__6, parameter_6, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x384xf16) <- (-1x144x384xf16, 384xf16)
        add__1 = paddle._C_ops.add_(matmul_0, parameter_7)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_2 = [slice_2, constant_8, constant_9, constant_10, constant_11]

        # pd_op.reshape_: (-1x144x3x4x32xf16, 0x-1x144x384xf16) <- (-1x144x384xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__8, reshape__9 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__1, combine_2), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x4x144x32xf16) <- (-1x144x3x4x32xf16)
        transpose_2 = paddle._C_ops.transpose(reshape__8, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x4x144x32xf16) <- (3x-1x4x144x32xf16, 1xi64, 1xi64)
        slice_3 = paddle._C_ops.slice(transpose_2, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x4x144x32xf16) <- (3x-1x4x144x32xf16, 1xi64, 1xi64)
        slice_4 = paddle._C_ops.slice(transpose_2, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x4x144x32xf16) <- (3x-1x4x144x32xf16, 1xi64, 1xi64)
        slice_5 = paddle._C_ops.slice(transpose_2, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x4x144x32xf16) <- (-1x4x144x32xf16, 1xf32)
        scale__0 = paddle._C_ops.scale_(slice_3, constant_14, float('0'), True)

        # pd_op.transpose: (-1x4x32x144xf16) <- (-1x4x144x32xf16)
        transpose_3 = paddle._C_ops.transpose(slice_4, [0, 1, 3, 2])

        # pd_op.matmul: (-1x4x144x144xf16) <- (-1x4x144x32xf16, -1x4x32x144xf16)
        matmul_1 = paddle.matmul(scale__0, transpose_3, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x4x144x144xf16) <- (-1x4x144x144xf16, 1x4x144x144xf16)
        add__2 = paddle._C_ops.add_(matmul_1, parameter_8)

        # pd_op.softmax_: (-1x4x144x144xf16) <- (-1x4x144x144xf16)
        softmax__0 = paddle._C_ops.softmax_(add__2, -1)

        # pd_op.matmul: (-1x4x144x32xf16) <- (-1x4x144x144xf16, -1x4x144x32xf16)
        matmul_2 = paddle.matmul(softmax__0, slice_5, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x4x32xf16) <- (-1x4x144x32xf16)
        transpose_4 = paddle._C_ops.transpose(matmul_2, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_3 = [slice_2, constant_8, constant_3]

        # pd_op.reshape_: (-1x144x128xf16, 0x-1x144x4x32xf16) <- (-1x144x4x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__10, reshape__11 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_4, combine_3), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x128xf16) <- (-1x144x128xf16, 128x128xf16)
        matmul_3 = paddle.matmul(reshape__10, parameter_9, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x128xf16) <- (-1x144x128xf16, 128xf16)
        add__3 = paddle._C_ops.add_(matmul_3, parameter_10)

        # pd_op.reshape_: (-1x12x12x128xf16, 0x-1x144x128xf16) <- (-1x144x128xf16, 4xi64)
        reshape__12, reshape__13 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__3, constant_6), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x8x8x12x12x128xf16, 0x-1x12x12x128xf16) <- (-1x12x12x128xf16, 6xi64)
        reshape__14, reshape__15 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__12, constant_15), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x8x12x8x12x128xf16) <- (-1x8x8x12x12x128xf16)
        transpose_5 = paddle._C_ops.transpose(reshape__14, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x96x96x128xf16, 0x-1x8x12x8x12x128xf16) <- (-1x8x12x8x12x128xf16, 4xi64)
        reshape__16, reshape__17 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_5, constant_16), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_4 = [slice_0, constant_17, constant_3]

        # pd_op.reshape_: (-1x9216x128xf16, 0x-1x96x96x128xf16) <- (-1x96x96x128xf16, [1xi32, 1xi32, 1xi32])
        reshape__18, reshape__19 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__16, combine_4), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x9216x128xf16) <- (-1x9216x128xf16, -1x9216x128xf16)
        add__4 = paddle._C_ops.add_(layer_norm_0, reshape__18)

        # pd_op.layer_norm: (-1x9216x128xf16, -9216xf32, -9216xf32) <- (-1x9216x128xf16, 128xf32, 128xf32)
        layer_norm_6, layer_norm_7, layer_norm_8 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__4, parameter_11, parameter_12, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x9216x512xf16) <- (-1x9216x128xf16, 128x512xf16)
        matmul_4 = paddle.matmul(layer_norm_6, parameter_13, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x9216x512xf16) <- (-1x9216x512xf16, 512xf16)
        add__5 = paddle._C_ops.add_(matmul_4, parameter_14)

        # pd_op.gelu: (-1x9216x512xf16) <- (-1x9216x512xf16)
        gelu_0 = paddle._C_ops.gelu(add__5, False)

        # pd_op.matmul: (-1x9216x128xf16) <- (-1x9216x512xf16, 512x128xf16)
        matmul_5 = paddle.matmul(gelu_0, parameter_15, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x9216x128xf16) <- (-1x9216x128xf16, 128xf16)
        add__6 = paddle._C_ops.add_(matmul_5, parameter_16)

        # pd_op.add_: (-1x9216x128xf16) <- (-1x9216x128xf16, -1x9216x128xf16)
        add__7 = paddle._C_ops.add_(add__4, add__6)

        # pd_op.shape: (3xi32) <- (-1x9216x128xf16)
        shape_3 = paddle._C_ops.shape(paddle.cast(add__7, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_6 = paddle._C_ops.slice(shape_3, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x9216x128xf16, -9216xf32, -9216xf32) <- (-1x9216x128xf16, 128xf32, 128xf32)
        layer_norm_9, layer_norm_10, layer_norm_11 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__7, parameter_17, parameter_18, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_5 = [slice_6, constant_2, constant_2, constant_3]

        # pd_op.reshape_: (-1x96x96x128xf16, 0x-1x9216x128xf16) <- (-1x9216x128xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__20, reshape__21 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_9, combine_5), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x96x96x128xf16) <- (-1x96x96x128xf16, 2xi64)
        roll_0 = paddle._C_ops.roll(reshape__20, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x96x96x128xf16)
        shape_4 = paddle._C_ops.shape(paddle.cast(roll_0, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_7 = paddle._C_ops.slice(shape_4, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_6 = [slice_7, constant_4, constant_5, constant_4, constant_5, constant_3]

        # pd_op.reshape_: (-1x8x12x8x12x128xf16, 0x-1x96x96x128xf16) <- (-1x96x96x128xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__22, reshape__23 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_0, combine_6), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x8x8x12x12x128xf16) <- (-1x8x12x8x12x128xf16)
        transpose_6 = paddle._C_ops.transpose(reshape__22, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x128xf16, 0x-1x8x8x12x12x128xf16) <- (-1x8x8x12x12x128xf16, 4xi64)
        reshape__24, reshape__25 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_6, constant_6), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x128xf16, 0x-1x12x12x128xf16) <- (-1x12x12x128xf16, 3xi64)
        reshape__26, reshape__27 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__24, constant_7), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x128xf16)
        shape_5 = paddle._C_ops.shape(paddle.cast(reshape__26, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_8 = paddle._C_ops.slice(shape_5, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x384xf16) <- (-1x144x128xf16, 128x384xf16)
        matmul_6 = paddle.matmul(reshape__26, parameter_19, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x384xf16) <- (-1x144x384xf16, 384xf16)
        add__8 = paddle._C_ops.add_(matmul_6, parameter_20)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_7 = [slice_8, constant_8, constant_9, constant_10, constant_11]

        # pd_op.reshape_: (-1x144x3x4x32xf16, 0x-1x144x384xf16) <- (-1x144x384xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__28, reshape__29 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__8, combine_7), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x4x144x32xf16) <- (-1x144x3x4x32xf16)
        transpose_7 = paddle._C_ops.transpose(reshape__28, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x4x144x32xf16) <- (3x-1x4x144x32xf16, 1xi64, 1xi64)
        slice_9 = paddle._C_ops.slice(transpose_7, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x4x144x32xf16) <- (3x-1x4x144x32xf16, 1xi64, 1xi64)
        slice_10 = paddle._C_ops.slice(transpose_7, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x4x144x32xf16) <- (3x-1x4x144x32xf16, 1xi64, 1xi64)
        slice_11 = paddle._C_ops.slice(transpose_7, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x4x144x32xf16) <- (-1x4x144x32xf16, 1xf32)
        scale__1 = paddle._C_ops.scale_(slice_9, constant_14, float('0'), True)

        # pd_op.transpose: (-1x4x32x144xf16) <- (-1x4x144x32xf16)
        transpose_8 = paddle._C_ops.transpose(slice_10, [0, 1, 3, 2])

        # pd_op.matmul: (-1x4x144x144xf16) <- (-1x4x144x32xf16, -1x4x32x144xf16)
        matmul_7 = paddle.matmul(scale__1, transpose_8, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x4x144x144xf16) <- (-1x4x144x144xf16, 1x4x144x144xf16)
        add__9 = paddle._C_ops.add_(matmul_7, parameter_21)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_0 = paddle._C_ops.memcpy_h2d(slice_8, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__0 = paddle._C_ops.floor_divide_(memcpy_h2d_0, parameter_22)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_8 = [floor_divide__0, constant_19, constant_10, constant_8, constant_8]

        # pd_op.reshape_: (-1x64x4x144x144xf16, 0x-1x4x144x144xf16) <- (-1x4x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__30, reshape__31 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__9, combine_8), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x64x4x144x144xf16) <- (-1x64x4x144x144xf16, 1x64x1x144x144xf16)
        add__10 = paddle._C_ops.add_(reshape__30, parameter_23)

        # pd_op.reshape_: (-1x4x144x144xf16, 0x-1x64x4x144x144xf16) <- (-1x64x4x144x144xf16, 4xi64)
        reshape__32, reshape__33 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__10, constant_20), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x4x144x144xf16) <- (-1x4x144x144xf16)
        softmax__1 = paddle._C_ops.softmax_(reshape__32, -1)

        # pd_op.matmul: (-1x4x144x32xf16) <- (-1x4x144x144xf16, -1x4x144x32xf16)
        matmul_8 = paddle.matmul(softmax__1, slice_11, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x4x32xf16) <- (-1x4x144x32xf16)
        transpose_9 = paddle._C_ops.transpose(matmul_8, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_9 = [slice_8, constant_8, constant_3]

        # pd_op.reshape_: (-1x144x128xf16, 0x-1x144x4x32xf16) <- (-1x144x4x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__34, reshape__35 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_9, combine_9), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x128xf16) <- (-1x144x128xf16, 128x128xf16)
        matmul_9 = paddle.matmul(reshape__34, parameter_24, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x128xf16) <- (-1x144x128xf16, 128xf16)
        add__11 = paddle._C_ops.add_(matmul_9, parameter_25)

        # pd_op.reshape_: (-1x12x12x128xf16, 0x-1x144x128xf16) <- (-1x144x128xf16, 4xi64)
        reshape__36, reshape__37 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__11, constant_6), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x8x8x12x12x128xf16, 0x-1x12x12x128xf16) <- (-1x12x12x128xf16, 6xi64)
        reshape__38, reshape__39 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__36, constant_15), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x8x12x8x12x128xf16) <- (-1x8x8x12x12x128xf16)
        transpose_10 = paddle._C_ops.transpose(reshape__38, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x96x96x128xf16, 0x-1x8x12x8x12x128xf16) <- (-1x8x12x8x12x128xf16, 4xi64)
        reshape__40, reshape__41 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_10, constant_16), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x96x96x128xf16) <- (-1x96x96x128xf16, 2xi64)
        roll_1 = paddle._C_ops.roll(reshape__40, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_10 = [slice_6, constant_17, constant_3]

        # pd_op.reshape_: (-1x9216x128xf16, 0x-1x96x96x128xf16) <- (-1x96x96x128xf16, [1xi32, 1xi32, 1xi32])
        reshape__42, reshape__43 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_1, combine_10), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x9216x128xf16) <- (-1x9216x128xf16, -1x9216x128xf16)
        add__12 = paddle._C_ops.add_(add__7, reshape__42)

        # pd_op.layer_norm: (-1x9216x128xf16, -9216xf32, -9216xf32) <- (-1x9216x128xf16, 128xf32, 128xf32)
        layer_norm_12, layer_norm_13, layer_norm_14 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__12, parameter_26, parameter_27, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x9216x512xf16) <- (-1x9216x128xf16, 128x512xf16)
        matmul_10 = paddle.matmul(layer_norm_12, parameter_28, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x9216x512xf16) <- (-1x9216x512xf16, 512xf16)
        add__13 = paddle._C_ops.add_(matmul_10, parameter_29)

        # pd_op.gelu: (-1x9216x512xf16) <- (-1x9216x512xf16)
        gelu_1 = paddle._C_ops.gelu(add__13, False)

        # pd_op.matmul: (-1x9216x128xf16) <- (-1x9216x512xf16, 512x128xf16)
        matmul_11 = paddle.matmul(gelu_1, parameter_30, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x9216x128xf16) <- (-1x9216x128xf16, 128xf16)
        add__14 = paddle._C_ops.add_(matmul_11, parameter_31)

        # pd_op.add_: (-1x9216x128xf16) <- (-1x9216x128xf16, -1x9216x128xf16)
        add__15 = paddle._C_ops.add_(add__12, add__14)

        # pd_op.shape: (3xi32) <- (-1x9216x128xf16)
        shape_6 = paddle._C_ops.shape(paddle.cast(add__15, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_12 = paddle._C_ops.slice(shape_6, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_11 = [slice_12, constant_22, constant_23, constant_22, constant_23, constant_3]

        # pd_op.reshape_: (-1x48x2x48x2x128xf16, 0x-1x9216x128xf16) <- (-1x9216x128xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__44, reshape__45 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__15, combine_11), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x48x48x2x2x128xf16) <- (-1x48x2x48x2x128xf16)
        transpose_11 = paddle._C_ops.transpose(reshape__44, [0, 1, 3, 4, 2, 5])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_12 = [slice_12, constant_24, constant_25]

        # pd_op.reshape_: (-1x2304x512xf16, 0x-1x48x48x2x2x128xf16) <- (-1x48x48x2x2x128xf16, [1xi32, 1xi32, 1xi32])
        reshape__46, reshape__47 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_11, combine_12), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.layer_norm: (-1x2304x512xf16, -2304xf32, -2304xf32) <- (-1x2304x512xf16, 512xf32, 512xf32)
        layer_norm_15, layer_norm_16, layer_norm_17 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(reshape__46, parameter_32, parameter_33, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x2304x256xf16) <- (-1x2304x512xf16, 512x256xf16)
        matmul_12 = paddle.matmul(layer_norm_15, parameter_34, transpose_x=False, transpose_y=False)

        # pd_op.shape: (3xi32) <- (-1x2304x256xf16)
        shape_7 = paddle._C_ops.shape(paddle.cast(matmul_12, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_13 = paddle._C_ops.slice(shape_7, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x2304x256xf16, -2304xf32, -2304xf32) <- (-1x2304x256xf16, 256xf32, 256xf32)
        layer_norm_18, layer_norm_19, layer_norm_20 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(matmul_12, parameter_35, parameter_36, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_13 = [slice_13, constant_22, constant_22, constant_26]

        # pd_op.reshape_: (-1x48x48x256xf16, 0x-1x2304x256xf16) <- (-1x2304x256xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__48, reshape__49 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_18, combine_13), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x48x48x256xf16)
        shape_8 = paddle._C_ops.shape(paddle.cast(reshape__48, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_14 = paddle._C_ops.slice(shape_8, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_14 = [slice_14, constant_10, constant_5, constant_10, constant_5, constant_26]

        # pd_op.reshape_: (-1x4x12x4x12x256xf16, 0x-1x48x48x256xf16) <- (-1x48x48x256xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__50, reshape__51 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__48, combine_14), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x4x4x12x12x256xf16) <- (-1x4x12x4x12x256xf16)
        transpose_12 = paddle._C_ops.transpose(reshape__50, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x256xf16, 0x-1x4x4x12x12x256xf16) <- (-1x4x4x12x12x256xf16, 4xi64)
        reshape__52, reshape__53 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_12, constant_27), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x256xf16, 0x-1x12x12x256xf16) <- (-1x12x12x256xf16, 3xi64)
        reshape__54, reshape__55 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__52, constant_28), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x256xf16)
        shape_9 = paddle._C_ops.shape(paddle.cast(reshape__54, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_15 = paddle._C_ops.slice(shape_9, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x768xf16) <- (-1x144x256xf16, 256x768xf16)
        matmul_13 = paddle.matmul(reshape__54, parameter_37, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x768xf16) <- (-1x144x768xf16, 768xf16)
        add__16 = paddle._C_ops.add_(matmul_13, parameter_38)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_15 = [slice_15, constant_8, constant_9, constant_4, constant_11]

        # pd_op.reshape_: (-1x144x3x8x32xf16, 0x-1x144x768xf16) <- (-1x144x768xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__56, reshape__57 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__16, combine_15), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x8x144x32xf16) <- (-1x144x3x8x32xf16)
        transpose_13 = paddle._C_ops.transpose(reshape__56, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x8x144x32xf16) <- (3x-1x8x144x32xf16, 1xi64, 1xi64)
        slice_16 = paddle._C_ops.slice(transpose_13, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x8x144x32xf16) <- (3x-1x8x144x32xf16, 1xi64, 1xi64)
        slice_17 = paddle._C_ops.slice(transpose_13, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x8x144x32xf16) <- (3x-1x8x144x32xf16, 1xi64, 1xi64)
        slice_18 = paddle._C_ops.slice(transpose_13, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x8x144x32xf16) <- (-1x8x144x32xf16, 1xf32)
        scale__2 = paddle._C_ops.scale_(slice_16, constant_14, float('0'), True)

        # pd_op.transpose: (-1x8x32x144xf16) <- (-1x8x144x32xf16)
        transpose_14 = paddle._C_ops.transpose(slice_17, [0, 1, 3, 2])

        # pd_op.matmul: (-1x8x144x144xf16) <- (-1x8x144x32xf16, -1x8x32x144xf16)
        matmul_14 = paddle.matmul(scale__2, transpose_14, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x8x144x144xf16) <- (-1x8x144x144xf16, 1x8x144x144xf16)
        add__17 = paddle._C_ops.add_(matmul_14, parameter_39)

        # pd_op.softmax_: (-1x8x144x144xf16) <- (-1x8x144x144xf16)
        softmax__2 = paddle._C_ops.softmax_(add__17, -1)

        # pd_op.matmul: (-1x8x144x32xf16) <- (-1x8x144x144xf16, -1x8x144x32xf16)
        matmul_15 = paddle.matmul(softmax__2, slice_18, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x8x32xf16) <- (-1x8x144x32xf16)
        transpose_15 = paddle._C_ops.transpose(matmul_15, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_16 = [slice_15, constant_8, constant_26]

        # pd_op.reshape_: (-1x144x256xf16, 0x-1x144x8x32xf16) <- (-1x144x8x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__58, reshape__59 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_15, combine_16), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x256xf16) <- (-1x144x256xf16, 256x256xf16)
        matmul_16 = paddle.matmul(reshape__58, parameter_40, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x256xf16) <- (-1x144x256xf16, 256xf16)
        add__18 = paddle._C_ops.add_(matmul_16, parameter_41)

        # pd_op.reshape_: (-1x12x12x256xf16, 0x-1x144x256xf16) <- (-1x144x256xf16, 4xi64)
        reshape__60, reshape__61 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__18, constant_27), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x4x4x12x12x256xf16, 0x-1x12x12x256xf16) <- (-1x12x12x256xf16, 6xi64)
        reshape__62, reshape__63 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__60, constant_29), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x4x12x4x12x256xf16) <- (-1x4x4x12x12x256xf16)
        transpose_16 = paddle._C_ops.transpose(reshape__62, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x48x48x256xf16, 0x-1x4x12x4x12x256xf16) <- (-1x4x12x4x12x256xf16, 4xi64)
        reshape__64, reshape__65 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_16, constant_30), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_17 = [slice_13, constant_24, constant_26]

        # pd_op.reshape_: (-1x2304x256xf16, 0x-1x48x48x256xf16) <- (-1x48x48x256xf16, [1xi32, 1xi32, 1xi32])
        reshape__66, reshape__67 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__64, combine_17), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x2304x256xf16) <- (-1x2304x256xf16, -1x2304x256xf16)
        add__19 = paddle._C_ops.add_(matmul_12, reshape__66)

        # pd_op.layer_norm: (-1x2304x256xf16, -2304xf32, -2304xf32) <- (-1x2304x256xf16, 256xf32, 256xf32)
        layer_norm_21, layer_norm_22, layer_norm_23 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__19, parameter_42, parameter_43, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x2304x1024xf16) <- (-1x2304x256xf16, 256x1024xf16)
        matmul_17 = paddle.matmul(layer_norm_21, parameter_44, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x2304x1024xf16) <- (-1x2304x1024xf16, 1024xf16)
        add__20 = paddle._C_ops.add_(matmul_17, parameter_45)

        # pd_op.gelu: (-1x2304x1024xf16) <- (-1x2304x1024xf16)
        gelu_2 = paddle._C_ops.gelu(add__20, False)

        # pd_op.matmul: (-1x2304x256xf16) <- (-1x2304x1024xf16, 1024x256xf16)
        matmul_18 = paddle.matmul(gelu_2, parameter_46, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x2304x256xf16) <- (-1x2304x256xf16, 256xf16)
        add__21 = paddle._C_ops.add_(matmul_18, parameter_47)

        # pd_op.add_: (-1x2304x256xf16) <- (-1x2304x256xf16, -1x2304x256xf16)
        add__22 = paddle._C_ops.add_(add__19, add__21)

        # pd_op.shape: (3xi32) <- (-1x2304x256xf16)
        shape_10 = paddle._C_ops.shape(paddle.cast(add__22, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_19 = paddle._C_ops.slice(shape_10, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x2304x256xf16, -2304xf32, -2304xf32) <- (-1x2304x256xf16, 256xf32, 256xf32)
        layer_norm_24, layer_norm_25, layer_norm_26 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__22, parameter_48, parameter_49, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_18 = [slice_19, constant_22, constant_22, constant_26]

        # pd_op.reshape_: (-1x48x48x256xf16, 0x-1x2304x256xf16) <- (-1x2304x256xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__68, reshape__69 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_24, combine_18), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x48x48x256xf16) <- (-1x48x48x256xf16, 2xi64)
        roll_2 = paddle._C_ops.roll(reshape__68, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x48x48x256xf16)
        shape_11 = paddle._C_ops.shape(paddle.cast(roll_2, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_20 = paddle._C_ops.slice(shape_11, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_19 = [slice_20, constant_10, constant_5, constant_10, constant_5, constant_26]

        # pd_op.reshape_: (-1x4x12x4x12x256xf16, 0x-1x48x48x256xf16) <- (-1x48x48x256xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__70, reshape__71 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_2, combine_19), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x4x4x12x12x256xf16) <- (-1x4x12x4x12x256xf16)
        transpose_17 = paddle._C_ops.transpose(reshape__70, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x256xf16, 0x-1x4x4x12x12x256xf16) <- (-1x4x4x12x12x256xf16, 4xi64)
        reshape__72, reshape__73 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_17, constant_27), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x256xf16, 0x-1x12x12x256xf16) <- (-1x12x12x256xf16, 3xi64)
        reshape__74, reshape__75 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__72, constant_28), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x256xf16)
        shape_12 = paddle._C_ops.shape(paddle.cast(reshape__74, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_21 = paddle._C_ops.slice(shape_12, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x768xf16) <- (-1x144x256xf16, 256x768xf16)
        matmul_19 = paddle.matmul(reshape__74, parameter_50, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x768xf16) <- (-1x144x768xf16, 768xf16)
        add__23 = paddle._C_ops.add_(matmul_19, parameter_51)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_20 = [slice_21, constant_8, constant_9, constant_4, constant_11]

        # pd_op.reshape_: (-1x144x3x8x32xf16, 0x-1x144x768xf16) <- (-1x144x768xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__76, reshape__77 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__23, combine_20), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x8x144x32xf16) <- (-1x144x3x8x32xf16)
        transpose_18 = paddle._C_ops.transpose(reshape__76, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x8x144x32xf16) <- (3x-1x8x144x32xf16, 1xi64, 1xi64)
        slice_22 = paddle._C_ops.slice(transpose_18, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x8x144x32xf16) <- (3x-1x8x144x32xf16, 1xi64, 1xi64)
        slice_23 = paddle._C_ops.slice(transpose_18, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x8x144x32xf16) <- (3x-1x8x144x32xf16, 1xi64, 1xi64)
        slice_24 = paddle._C_ops.slice(transpose_18, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x8x144x32xf16) <- (-1x8x144x32xf16, 1xf32)
        scale__3 = paddle._C_ops.scale_(slice_22, constant_14, float('0'), True)

        # pd_op.transpose: (-1x8x32x144xf16) <- (-1x8x144x32xf16)
        transpose_19 = paddle._C_ops.transpose(slice_23, [0, 1, 3, 2])

        # pd_op.matmul: (-1x8x144x144xf16) <- (-1x8x144x32xf16, -1x8x32x144xf16)
        matmul_20 = paddle.matmul(scale__3, transpose_19, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x8x144x144xf16) <- (-1x8x144x144xf16, 1x8x144x144xf16)
        add__24 = paddle._C_ops.add_(matmul_20, parameter_52)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_1 = paddle._C_ops.memcpy_h2d(slice_21, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__1 = paddle._C_ops.floor_divide_(memcpy_h2d_1, parameter_53)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_21 = [floor_divide__1, constant_31, constant_4, constant_8, constant_8]

        # pd_op.reshape_: (-1x16x8x144x144xf16, 0x-1x8x144x144xf16) <- (-1x8x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__78, reshape__79 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__24, combine_21), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x16x8x144x144xf16) <- (-1x16x8x144x144xf16, 1x16x1x144x144xf16)
        add__25 = paddle._C_ops.add_(reshape__78, parameter_54)

        # pd_op.reshape_: (-1x8x144x144xf16, 0x-1x16x8x144x144xf16) <- (-1x16x8x144x144xf16, 4xi64)
        reshape__80, reshape__81 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__25, constant_32), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x8x144x144xf16) <- (-1x8x144x144xf16)
        softmax__3 = paddle._C_ops.softmax_(reshape__80, -1)

        # pd_op.matmul: (-1x8x144x32xf16) <- (-1x8x144x144xf16, -1x8x144x32xf16)
        matmul_21 = paddle.matmul(softmax__3, slice_24, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x8x32xf16) <- (-1x8x144x32xf16)
        transpose_20 = paddle._C_ops.transpose(matmul_21, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_22 = [slice_21, constant_8, constant_26]

        # pd_op.reshape_: (-1x144x256xf16, 0x-1x144x8x32xf16) <- (-1x144x8x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__82, reshape__83 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_20, combine_22), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x256xf16) <- (-1x144x256xf16, 256x256xf16)
        matmul_22 = paddle.matmul(reshape__82, parameter_55, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x256xf16) <- (-1x144x256xf16, 256xf16)
        add__26 = paddle._C_ops.add_(matmul_22, parameter_56)

        # pd_op.reshape_: (-1x12x12x256xf16, 0x-1x144x256xf16) <- (-1x144x256xf16, 4xi64)
        reshape__84, reshape__85 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__26, constant_27), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x4x4x12x12x256xf16, 0x-1x12x12x256xf16) <- (-1x12x12x256xf16, 6xi64)
        reshape__86, reshape__87 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__84, constant_29), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x4x12x4x12x256xf16) <- (-1x4x4x12x12x256xf16)
        transpose_21 = paddle._C_ops.transpose(reshape__86, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x48x48x256xf16, 0x-1x4x12x4x12x256xf16) <- (-1x4x12x4x12x256xf16, 4xi64)
        reshape__88, reshape__89 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_21, constant_30), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x48x48x256xf16) <- (-1x48x48x256xf16, 2xi64)
        roll_3 = paddle._C_ops.roll(reshape__88, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_23 = [slice_19, constant_24, constant_26]

        # pd_op.reshape_: (-1x2304x256xf16, 0x-1x48x48x256xf16) <- (-1x48x48x256xf16, [1xi32, 1xi32, 1xi32])
        reshape__90, reshape__91 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_3, combine_23), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x2304x256xf16) <- (-1x2304x256xf16, -1x2304x256xf16)
        add__27 = paddle._C_ops.add_(add__22, reshape__90)

        # pd_op.layer_norm: (-1x2304x256xf16, -2304xf32, -2304xf32) <- (-1x2304x256xf16, 256xf32, 256xf32)
        layer_norm_27, layer_norm_28, layer_norm_29 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__27, parameter_57, parameter_58, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x2304x1024xf16) <- (-1x2304x256xf16, 256x1024xf16)
        matmul_23 = paddle.matmul(layer_norm_27, parameter_59, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x2304x1024xf16) <- (-1x2304x1024xf16, 1024xf16)
        add__28 = paddle._C_ops.add_(matmul_23, parameter_60)

        # pd_op.gelu: (-1x2304x1024xf16) <- (-1x2304x1024xf16)
        gelu_3 = paddle._C_ops.gelu(add__28, False)

        # pd_op.matmul: (-1x2304x256xf16) <- (-1x2304x1024xf16, 1024x256xf16)
        matmul_24 = paddle.matmul(gelu_3, parameter_61, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x2304x256xf16) <- (-1x2304x256xf16, 256xf16)
        add__29 = paddle._C_ops.add_(matmul_24, parameter_62)

        # pd_op.add_: (-1x2304x256xf16) <- (-1x2304x256xf16, -1x2304x256xf16)
        add__30 = paddle._C_ops.add_(add__27, add__29)

        # pd_op.shape: (3xi32) <- (-1x2304x256xf16)
        shape_13 = paddle._C_ops.shape(paddle.cast(add__30, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_25 = paddle._C_ops.slice(shape_13, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_24 = [slice_25, constant_33, constant_23, constant_33, constant_23, constant_26]

        # pd_op.reshape_: (-1x24x2x24x2x256xf16, 0x-1x2304x256xf16) <- (-1x2304x256xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__92, reshape__93 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__30, combine_24), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x24x24x2x2x256xf16) <- (-1x24x2x24x2x256xf16)
        transpose_22 = paddle._C_ops.transpose(reshape__92, [0, 1, 3, 4, 2, 5])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_25 = [slice_25, constant_34, constant_35]

        # pd_op.reshape_: (-1x576x1024xf16, 0x-1x24x24x2x2x256xf16) <- (-1x24x24x2x2x256xf16, [1xi32, 1xi32, 1xi32])
        reshape__94, reshape__95 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_22, combine_25), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.layer_norm: (-1x576x1024xf16, -576xf32, -576xf32) <- (-1x576x1024xf16, 1024xf32, 1024xf32)
        layer_norm_30, layer_norm_31, layer_norm_32 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(reshape__94, parameter_63, parameter_64, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x1024xf16, 1024x512xf16)
        matmul_25 = paddle.matmul(layer_norm_30, parameter_65, transpose_x=False, transpose_y=False)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_14 = paddle._C_ops.shape(paddle.cast(matmul_25, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_26 = paddle._C_ops.slice(shape_14, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_33, layer_norm_34, layer_norm_35 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(matmul_25, parameter_66, parameter_67, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_26 = [slice_26, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__96, reshape__97 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_33, combine_26), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_15 = paddle._C_ops.shape(paddle.cast(reshape__96, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_27 = paddle._C_ops.slice(shape_15, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_27 = [slice_27, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__98, reshape__99 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__96, combine_27), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_23 = paddle._C_ops.transpose(reshape__98, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__100, reshape__101 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_23, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__102, reshape__103 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__100, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_16 = paddle._C_ops.shape(paddle.cast(reshape__102, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_28 = paddle._C_ops.slice(shape_16, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_26 = paddle.matmul(reshape__102, parameter_68, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__31 = paddle._C_ops.add_(matmul_26, parameter_69)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_28 = [slice_28, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__104, reshape__105 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__31, combine_28), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_24 = paddle._C_ops.transpose(reshape__104, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_29 = paddle._C_ops.slice(transpose_24, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_30 = paddle._C_ops.slice(transpose_24, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_31 = paddle._C_ops.slice(transpose_24, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__4 = paddle._C_ops.scale_(slice_29, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_25 = paddle._C_ops.transpose(slice_30, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_27 = paddle.matmul(scale__4, transpose_25, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__32 = paddle._C_ops.add_(matmul_27, parameter_70)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__4 = paddle._C_ops.softmax_(add__32, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_28 = paddle.matmul(softmax__4, slice_31, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_26 = paddle._C_ops.transpose(matmul_28, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_29 = [slice_28, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__106, reshape__107 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_26, combine_29), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_29 = paddle.matmul(reshape__106, parameter_71, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__33 = paddle._C_ops.add_(matmul_29, parameter_72)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__108, reshape__109 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__33, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__110, reshape__111 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__108, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_27 = paddle._C_ops.transpose(reshape__110, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__112, reshape__113 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_27, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_30 = [slice_26, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__114, reshape__115 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__112, combine_30), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__34 = paddle._C_ops.add_(matmul_25, reshape__114)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_36, layer_norm_37, layer_norm_38 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__34, parameter_73, parameter_74, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_30 = paddle.matmul(layer_norm_36, parameter_75, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__35 = paddle._C_ops.add_(matmul_30, parameter_76)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_4 = paddle._C_ops.gelu(add__35, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_31 = paddle.matmul(gelu_4, parameter_77, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__36 = paddle._C_ops.add_(matmul_31, parameter_78)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__37 = paddle._C_ops.add_(add__34, add__36)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_17 = paddle._C_ops.shape(paddle.cast(add__37, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_32 = paddle._C_ops.slice(shape_17, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_39, layer_norm_40, layer_norm_41 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__37, parameter_79, parameter_80, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_31 = [slice_32, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__116, reshape__117 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_39, combine_31), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_4 = paddle._C_ops.roll(reshape__116, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_18 = paddle._C_ops.shape(paddle.cast(roll_4, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_33 = paddle._C_ops.slice(shape_18, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_32 = [slice_33, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__118, reshape__119 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_4, combine_32), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_28 = paddle._C_ops.transpose(reshape__118, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__120, reshape__121 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_28, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__122, reshape__123 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__120, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_19 = paddle._C_ops.shape(paddle.cast(reshape__122, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_34 = paddle._C_ops.slice(shape_19, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_32 = paddle.matmul(reshape__122, parameter_81, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__38 = paddle._C_ops.add_(matmul_32, parameter_82)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_33 = [slice_34, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__124, reshape__125 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__38, combine_33), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_29 = paddle._C_ops.transpose(reshape__124, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_35 = paddle._C_ops.slice(transpose_29, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_36 = paddle._C_ops.slice(transpose_29, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_37 = paddle._C_ops.slice(transpose_29, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__5 = paddle._C_ops.scale_(slice_35, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_30 = paddle._C_ops.transpose(slice_36, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_33 = paddle.matmul(scale__5, transpose_30, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__39 = paddle._C_ops.add_(matmul_33, parameter_83)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_2 = paddle._C_ops.memcpy_h2d(slice_34, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__2 = paddle._C_ops.floor_divide_(memcpy_h2d_2, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_34 = [floor_divide__2, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__126, reshape__127 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__39, combine_34), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__40 = paddle._C_ops.add_(reshape__126, parameter_85)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__128, reshape__129 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__40, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__5 = paddle._C_ops.softmax_(reshape__128, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_34 = paddle.matmul(softmax__5, slice_37, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_31 = paddle._C_ops.transpose(matmul_34, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_35 = [slice_34, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__130, reshape__131 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_31, combine_35), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_35 = paddle.matmul(reshape__130, parameter_86, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__41 = paddle._C_ops.add_(matmul_35, parameter_87)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__132, reshape__133 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__41, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__134, reshape__135 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__132, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_32 = paddle._C_ops.transpose(reshape__134, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__136, reshape__137 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_32, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_5 = paddle._C_ops.roll(reshape__136, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_36 = [slice_32, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__138, reshape__139 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_5, combine_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__42 = paddle._C_ops.add_(add__37, reshape__138)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_42, layer_norm_43, layer_norm_44 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__42, parameter_88, parameter_89, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_36 = paddle.matmul(layer_norm_42, parameter_90, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__43 = paddle._C_ops.add_(matmul_36, parameter_91)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_5 = paddle._C_ops.gelu(add__43, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_37 = paddle.matmul(gelu_5, parameter_92, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__44 = paddle._C_ops.add_(matmul_37, parameter_93)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__45 = paddle._C_ops.add_(add__42, add__44)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_20 = paddle._C_ops.shape(paddle.cast(add__45, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_38 = paddle._C_ops.slice(shape_20, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_45, layer_norm_46, layer_norm_47 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__45, parameter_94, parameter_95, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_37 = [slice_38, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__140, reshape__141 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_45, combine_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_21 = paddle._C_ops.shape(paddle.cast(reshape__140, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_39 = paddle._C_ops.slice(shape_21, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_38 = [slice_39, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__142, reshape__143 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__140, combine_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_33 = paddle._C_ops.transpose(reshape__142, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__144, reshape__145 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_33, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__146, reshape__147 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__144, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_22 = paddle._C_ops.shape(paddle.cast(reshape__146, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_40 = paddle._C_ops.slice(shape_22, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_38 = paddle.matmul(reshape__146, parameter_96, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__46 = paddle._C_ops.add_(matmul_38, parameter_97)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_39 = [slice_40, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__148, reshape__149 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__46, combine_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_34 = paddle._C_ops.transpose(reshape__148, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_41 = paddle._C_ops.slice(transpose_34, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_42 = paddle._C_ops.slice(transpose_34, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_43 = paddle._C_ops.slice(transpose_34, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__6 = paddle._C_ops.scale_(slice_41, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_35 = paddle._C_ops.transpose(slice_42, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_39 = paddle.matmul(scale__6, transpose_35, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__47 = paddle._C_ops.add_(matmul_39, parameter_98)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__6 = paddle._C_ops.softmax_(add__47, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_40 = paddle.matmul(softmax__6, slice_43, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_36 = paddle._C_ops.transpose(matmul_40, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_40 = [slice_40, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__150, reshape__151 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_36, combine_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_41 = paddle.matmul(reshape__150, parameter_99, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__48 = paddle._C_ops.add_(matmul_41, parameter_100)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__152, reshape__153 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__48, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__154, reshape__155 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__152, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_37 = paddle._C_ops.transpose(reshape__154, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__156, reshape__157 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_37, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_41 = [slice_38, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__158, reshape__159 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__156, combine_41), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__49 = paddle._C_ops.add_(add__45, reshape__158)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_48, layer_norm_49, layer_norm_50 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__49, parameter_101, parameter_102, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_42 = paddle.matmul(layer_norm_48, parameter_103, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__50 = paddle._C_ops.add_(matmul_42, parameter_104)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_6 = paddle._C_ops.gelu(add__50, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_43 = paddle.matmul(gelu_6, parameter_105, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__51 = paddle._C_ops.add_(matmul_43, parameter_106)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__52 = paddle._C_ops.add_(add__49, add__51)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_23 = paddle._C_ops.shape(paddle.cast(add__52, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_44 = paddle._C_ops.slice(shape_23, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_51, layer_norm_52, layer_norm_53 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__52, parameter_107, parameter_108, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_42 = [slice_44, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__160, reshape__161 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_51, combine_42), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_6 = paddle._C_ops.roll(reshape__160, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_24 = paddle._C_ops.shape(paddle.cast(roll_6, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_45 = paddle._C_ops.slice(shape_24, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_43 = [slice_45, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__162, reshape__163 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_6, combine_43), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_38 = paddle._C_ops.transpose(reshape__162, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__164, reshape__165 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_38, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__166, reshape__167 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__164, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_25 = paddle._C_ops.shape(paddle.cast(reshape__166, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_46 = paddle._C_ops.slice(shape_25, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_44 = paddle.matmul(reshape__166, parameter_109, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__53 = paddle._C_ops.add_(matmul_44, parameter_110)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_44 = [slice_46, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__168, reshape__169 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__53, combine_44), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_39 = paddle._C_ops.transpose(reshape__168, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_47 = paddle._C_ops.slice(transpose_39, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_48 = paddle._C_ops.slice(transpose_39, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_49 = paddle._C_ops.slice(transpose_39, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__7 = paddle._C_ops.scale_(slice_47, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_40 = paddle._C_ops.transpose(slice_48, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_45 = paddle.matmul(scale__7, transpose_40, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__54 = paddle._C_ops.add_(matmul_45, parameter_111)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_3 = paddle._C_ops.memcpy_h2d(slice_46, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__3 = paddle._C_ops.floor_divide_(memcpy_h2d_3, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_45 = [floor_divide__3, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__170, reshape__171 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__54, combine_45), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__55 = paddle._C_ops.add_(reshape__170, parameter_112)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__172, reshape__173 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__55, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__7 = paddle._C_ops.softmax_(reshape__172, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_46 = paddle.matmul(softmax__7, slice_49, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_41 = paddle._C_ops.transpose(matmul_46, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_46 = [slice_46, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__174, reshape__175 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_41, combine_46), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_47 = paddle.matmul(reshape__174, parameter_113, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__56 = paddle._C_ops.add_(matmul_47, parameter_114)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__176, reshape__177 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__56, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__178, reshape__179 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__176, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_42 = paddle._C_ops.transpose(reshape__178, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__180, reshape__181 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_42, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_7 = paddle._C_ops.roll(reshape__180, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_47 = [slice_44, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__182, reshape__183 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_7, combine_47), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__57 = paddle._C_ops.add_(add__52, reshape__182)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_54, layer_norm_55, layer_norm_56 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__57, parameter_115, parameter_116, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_48 = paddle.matmul(layer_norm_54, parameter_117, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__58 = paddle._C_ops.add_(matmul_48, parameter_118)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_7 = paddle._C_ops.gelu(add__58, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_49 = paddle.matmul(gelu_7, parameter_119, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__59 = paddle._C_ops.add_(matmul_49, parameter_120)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__60 = paddle._C_ops.add_(add__57, add__59)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_26 = paddle._C_ops.shape(paddle.cast(add__60, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_50 = paddle._C_ops.slice(shape_26, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_57, layer_norm_58, layer_norm_59 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__60, parameter_121, parameter_122, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_48 = [slice_50, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__184, reshape__185 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_57, combine_48), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_27 = paddle._C_ops.shape(paddle.cast(reshape__184, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_51 = paddle._C_ops.slice(shape_27, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_49 = [slice_51, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__186, reshape__187 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__184, combine_49), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_43 = paddle._C_ops.transpose(reshape__186, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__188, reshape__189 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_43, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__190, reshape__191 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__188, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_28 = paddle._C_ops.shape(paddle.cast(reshape__190, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_52 = paddle._C_ops.slice(shape_28, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_50 = paddle.matmul(reshape__190, parameter_123, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__61 = paddle._C_ops.add_(matmul_50, parameter_124)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_50 = [slice_52, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__192, reshape__193 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__61, combine_50), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_44 = paddle._C_ops.transpose(reshape__192, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_53 = paddle._C_ops.slice(transpose_44, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_54 = paddle._C_ops.slice(transpose_44, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_55 = paddle._C_ops.slice(transpose_44, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__8 = paddle._C_ops.scale_(slice_53, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_45 = paddle._C_ops.transpose(slice_54, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_51 = paddle.matmul(scale__8, transpose_45, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__62 = paddle._C_ops.add_(matmul_51, parameter_125)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__8 = paddle._C_ops.softmax_(add__62, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_52 = paddle.matmul(softmax__8, slice_55, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_46 = paddle._C_ops.transpose(matmul_52, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_51 = [slice_52, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__194, reshape__195 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_46, combine_51), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_53 = paddle.matmul(reshape__194, parameter_126, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__63 = paddle._C_ops.add_(matmul_53, parameter_127)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__196, reshape__197 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__63, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__198, reshape__199 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__196, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_47 = paddle._C_ops.transpose(reshape__198, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__200, reshape__201 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_47, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_52 = [slice_50, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__202, reshape__203 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__200, combine_52), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__64 = paddle._C_ops.add_(add__60, reshape__202)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_60, layer_norm_61, layer_norm_62 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__64, parameter_128, parameter_129, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_54 = paddle.matmul(layer_norm_60, parameter_130, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__65 = paddle._C_ops.add_(matmul_54, parameter_131)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_8 = paddle._C_ops.gelu(add__65, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_55 = paddle.matmul(gelu_8, parameter_132, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__66 = paddle._C_ops.add_(matmul_55, parameter_133)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__67 = paddle._C_ops.add_(add__64, add__66)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_29 = paddle._C_ops.shape(paddle.cast(add__67, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_56 = paddle._C_ops.slice(shape_29, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_63, layer_norm_64, layer_norm_65 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__67, parameter_134, parameter_135, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_53 = [slice_56, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__204, reshape__205 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_63, combine_53), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_8 = paddle._C_ops.roll(reshape__204, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_30 = paddle._C_ops.shape(paddle.cast(roll_8, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_57 = paddle._C_ops.slice(shape_30, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_54 = [slice_57, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__206, reshape__207 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_8, combine_54), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_48 = paddle._C_ops.transpose(reshape__206, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__208, reshape__209 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_48, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__210, reshape__211 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__208, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_31 = paddle._C_ops.shape(paddle.cast(reshape__210, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_58 = paddle._C_ops.slice(shape_31, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_56 = paddle.matmul(reshape__210, parameter_136, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__68 = paddle._C_ops.add_(matmul_56, parameter_137)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_55 = [slice_58, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__212, reshape__213 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__68, combine_55), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_49 = paddle._C_ops.transpose(reshape__212, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_59 = paddle._C_ops.slice(transpose_49, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_60 = paddle._C_ops.slice(transpose_49, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_61 = paddle._C_ops.slice(transpose_49, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__9 = paddle._C_ops.scale_(slice_59, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_50 = paddle._C_ops.transpose(slice_60, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_57 = paddle.matmul(scale__9, transpose_50, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__69 = paddle._C_ops.add_(matmul_57, parameter_138)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_4 = paddle._C_ops.memcpy_h2d(slice_58, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__4 = paddle._C_ops.floor_divide_(memcpy_h2d_4, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_56 = [floor_divide__4, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__214, reshape__215 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__69, combine_56), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__70 = paddle._C_ops.add_(reshape__214, parameter_139)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__216, reshape__217 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__70, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__9 = paddle._C_ops.softmax_(reshape__216, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_58 = paddle.matmul(softmax__9, slice_61, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_51 = paddle._C_ops.transpose(matmul_58, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_57 = [slice_58, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__218, reshape__219 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_51, combine_57), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_59 = paddle.matmul(reshape__218, parameter_140, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__71 = paddle._C_ops.add_(matmul_59, parameter_141)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__220, reshape__221 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__71, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__222, reshape__223 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__220, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_52 = paddle._C_ops.transpose(reshape__222, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__224, reshape__225 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_52, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_9 = paddle._C_ops.roll(reshape__224, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_58 = [slice_56, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__226, reshape__227 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_9, combine_58), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__72 = paddle._C_ops.add_(add__67, reshape__226)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_66, layer_norm_67, layer_norm_68 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__72, parameter_142, parameter_143, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_60 = paddle.matmul(layer_norm_66, parameter_144, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__73 = paddle._C_ops.add_(matmul_60, parameter_145)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_9 = paddle._C_ops.gelu(add__73, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_61 = paddle.matmul(gelu_9, parameter_146, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__74 = paddle._C_ops.add_(matmul_61, parameter_147)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__75 = paddle._C_ops.add_(add__72, add__74)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_32 = paddle._C_ops.shape(paddle.cast(add__75, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_62 = paddle._C_ops.slice(shape_32, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_69, layer_norm_70, layer_norm_71 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__75, parameter_148, parameter_149, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_59 = [slice_62, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__228, reshape__229 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_69, combine_59), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_33 = paddle._C_ops.shape(paddle.cast(reshape__228, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_63 = paddle._C_ops.slice(shape_33, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_60 = [slice_63, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__230, reshape__231 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__228, combine_60), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_53 = paddle._C_ops.transpose(reshape__230, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__232, reshape__233 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_53, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__234, reshape__235 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__232, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_34 = paddle._C_ops.shape(paddle.cast(reshape__234, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_64 = paddle._C_ops.slice(shape_34, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_62 = paddle.matmul(reshape__234, parameter_150, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__76 = paddle._C_ops.add_(matmul_62, parameter_151)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_61 = [slice_64, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__236, reshape__237 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__76, combine_61), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_54 = paddle._C_ops.transpose(reshape__236, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_65 = paddle._C_ops.slice(transpose_54, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_66 = paddle._C_ops.slice(transpose_54, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_67 = paddle._C_ops.slice(transpose_54, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__10 = paddle._C_ops.scale_(slice_65, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_55 = paddle._C_ops.transpose(slice_66, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_63 = paddle.matmul(scale__10, transpose_55, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__77 = paddle._C_ops.add_(matmul_63, parameter_152)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__10 = paddle._C_ops.softmax_(add__77, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_64 = paddle.matmul(softmax__10, slice_67, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_56 = paddle._C_ops.transpose(matmul_64, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_62 = [slice_64, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__238, reshape__239 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_56, combine_62), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_65 = paddle.matmul(reshape__238, parameter_153, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__78 = paddle._C_ops.add_(matmul_65, parameter_154)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__240, reshape__241 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__78, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__242, reshape__243 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__240, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_57 = paddle._C_ops.transpose(reshape__242, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__244, reshape__245 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_57, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_63 = [slice_62, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__246, reshape__247 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__244, combine_63), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__79 = paddle._C_ops.add_(add__75, reshape__246)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_72, layer_norm_73, layer_norm_74 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__79, parameter_155, parameter_156, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_66 = paddle.matmul(layer_norm_72, parameter_157, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__80 = paddle._C_ops.add_(matmul_66, parameter_158)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_10 = paddle._C_ops.gelu(add__80, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_67 = paddle.matmul(gelu_10, parameter_159, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__81 = paddle._C_ops.add_(matmul_67, parameter_160)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__82 = paddle._C_ops.add_(add__79, add__81)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_35 = paddle._C_ops.shape(paddle.cast(add__82, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_68 = paddle._C_ops.slice(shape_35, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_75, layer_norm_76, layer_norm_77 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__82, parameter_161, parameter_162, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_64 = [slice_68, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__248, reshape__249 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_75, combine_64), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_10 = paddle._C_ops.roll(reshape__248, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_36 = paddle._C_ops.shape(paddle.cast(roll_10, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_69 = paddle._C_ops.slice(shape_36, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_65 = [slice_69, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__250, reshape__251 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_10, combine_65), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_58 = paddle._C_ops.transpose(reshape__250, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__252, reshape__253 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_58, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__254, reshape__255 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__252, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_37 = paddle._C_ops.shape(paddle.cast(reshape__254, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_70 = paddle._C_ops.slice(shape_37, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_68 = paddle.matmul(reshape__254, parameter_163, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__83 = paddle._C_ops.add_(matmul_68, parameter_164)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_66 = [slice_70, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__256, reshape__257 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__83, combine_66), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_59 = paddle._C_ops.transpose(reshape__256, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_71 = paddle._C_ops.slice(transpose_59, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_72 = paddle._C_ops.slice(transpose_59, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_73 = paddle._C_ops.slice(transpose_59, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__11 = paddle._C_ops.scale_(slice_71, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_60 = paddle._C_ops.transpose(slice_72, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_69 = paddle.matmul(scale__11, transpose_60, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__84 = paddle._C_ops.add_(matmul_69, parameter_165)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_5 = paddle._C_ops.memcpy_h2d(slice_70, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__5 = paddle._C_ops.floor_divide_(memcpy_h2d_5, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_67 = [floor_divide__5, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__258, reshape__259 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__84, combine_67), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__85 = paddle._C_ops.add_(reshape__258, parameter_166)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__260, reshape__261 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__85, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__11 = paddle._C_ops.softmax_(reshape__260, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_70 = paddle.matmul(softmax__11, slice_73, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_61 = paddle._C_ops.transpose(matmul_70, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_68 = [slice_70, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__262, reshape__263 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_61, combine_68), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_71 = paddle.matmul(reshape__262, parameter_167, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__86 = paddle._C_ops.add_(matmul_71, parameter_168)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__264, reshape__265 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__86, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__266, reshape__267 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__264, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_62 = paddle._C_ops.transpose(reshape__266, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__268, reshape__269 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_62, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_11 = paddle._C_ops.roll(reshape__268, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_69 = [slice_68, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__270, reshape__271 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_11, combine_69), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__87 = paddle._C_ops.add_(add__82, reshape__270)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_78, layer_norm_79, layer_norm_80 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__87, parameter_169, parameter_170, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_72 = paddle.matmul(layer_norm_78, parameter_171, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__88 = paddle._C_ops.add_(matmul_72, parameter_172)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_11 = paddle._C_ops.gelu(add__88, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_73 = paddle.matmul(gelu_11, parameter_173, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__89 = paddle._C_ops.add_(matmul_73, parameter_174)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__90 = paddle._C_ops.add_(add__87, add__89)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_38 = paddle._C_ops.shape(paddle.cast(add__90, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_74 = paddle._C_ops.slice(shape_38, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_81, layer_norm_82, layer_norm_83 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__90, parameter_175, parameter_176, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_70 = [slice_74, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__272, reshape__273 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_81, combine_70), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_39 = paddle._C_ops.shape(paddle.cast(reshape__272, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_75 = paddle._C_ops.slice(shape_39, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_71 = [slice_75, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__274, reshape__275 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__272, combine_71), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_63 = paddle._C_ops.transpose(reshape__274, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__276, reshape__277 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_63, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__278, reshape__279 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__276, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_40 = paddle._C_ops.shape(paddle.cast(reshape__278, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_76 = paddle._C_ops.slice(shape_40, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_74 = paddle.matmul(reshape__278, parameter_177, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__91 = paddle._C_ops.add_(matmul_74, parameter_178)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_72 = [slice_76, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__280, reshape__281 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__91, combine_72), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_64 = paddle._C_ops.transpose(reshape__280, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_77 = paddle._C_ops.slice(transpose_64, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_78 = paddle._C_ops.slice(transpose_64, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_79 = paddle._C_ops.slice(transpose_64, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__12 = paddle._C_ops.scale_(slice_77, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_65 = paddle._C_ops.transpose(slice_78, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_75 = paddle.matmul(scale__12, transpose_65, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__92 = paddle._C_ops.add_(matmul_75, parameter_179)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__12 = paddle._C_ops.softmax_(add__92, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_76 = paddle.matmul(softmax__12, slice_79, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_66 = paddle._C_ops.transpose(matmul_76, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_73 = [slice_76, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__282, reshape__283 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_66, combine_73), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_77 = paddle.matmul(reshape__282, parameter_180, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__93 = paddle._C_ops.add_(matmul_77, parameter_181)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__284, reshape__285 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__93, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__286, reshape__287 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__284, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_67 = paddle._C_ops.transpose(reshape__286, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__288, reshape__289 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_67, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_74 = [slice_74, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__290, reshape__291 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__288, combine_74), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__94 = paddle._C_ops.add_(add__90, reshape__290)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_84, layer_norm_85, layer_norm_86 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__94, parameter_182, parameter_183, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_78 = paddle.matmul(layer_norm_84, parameter_184, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__95 = paddle._C_ops.add_(matmul_78, parameter_185)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_12 = paddle._C_ops.gelu(add__95, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_79 = paddle.matmul(gelu_12, parameter_186, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__96 = paddle._C_ops.add_(matmul_79, parameter_187)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__97 = paddle._C_ops.add_(add__94, add__96)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_41 = paddle._C_ops.shape(paddle.cast(add__97, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_80 = paddle._C_ops.slice(shape_41, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_87, layer_norm_88, layer_norm_89 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__97, parameter_188, parameter_189, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_75 = [slice_80, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__292, reshape__293 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_87, combine_75), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_12 = paddle._C_ops.roll(reshape__292, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_42 = paddle._C_ops.shape(paddle.cast(roll_12, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_81 = paddle._C_ops.slice(shape_42, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_76 = [slice_81, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__294, reshape__295 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_12, combine_76), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_68 = paddle._C_ops.transpose(reshape__294, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__296, reshape__297 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_68, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__298, reshape__299 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__296, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_43 = paddle._C_ops.shape(paddle.cast(reshape__298, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_82 = paddle._C_ops.slice(shape_43, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_80 = paddle.matmul(reshape__298, parameter_190, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__98 = paddle._C_ops.add_(matmul_80, parameter_191)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_77 = [slice_82, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__300, reshape__301 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__98, combine_77), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_69 = paddle._C_ops.transpose(reshape__300, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_83 = paddle._C_ops.slice(transpose_69, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_84 = paddle._C_ops.slice(transpose_69, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_85 = paddle._C_ops.slice(transpose_69, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__13 = paddle._C_ops.scale_(slice_83, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_70 = paddle._C_ops.transpose(slice_84, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_81 = paddle.matmul(scale__13, transpose_70, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__99 = paddle._C_ops.add_(matmul_81, parameter_192)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_6 = paddle._C_ops.memcpy_h2d(slice_82, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__6 = paddle._C_ops.floor_divide_(memcpy_h2d_6, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_78 = [floor_divide__6, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__302, reshape__303 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__99, combine_78), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__100 = paddle._C_ops.add_(reshape__302, parameter_193)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__304, reshape__305 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__100, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__13 = paddle._C_ops.softmax_(reshape__304, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_82 = paddle.matmul(softmax__13, slice_85, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_71 = paddle._C_ops.transpose(matmul_82, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_79 = [slice_82, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__306, reshape__307 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_71, combine_79), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_83 = paddle.matmul(reshape__306, parameter_194, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__101 = paddle._C_ops.add_(matmul_83, parameter_195)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__308, reshape__309 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__101, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__310, reshape__311 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__308, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_72 = paddle._C_ops.transpose(reshape__310, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__312, reshape__313 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_72, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_13 = paddle._C_ops.roll(reshape__312, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_80 = [slice_80, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__314, reshape__315 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_13, combine_80), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__102 = paddle._C_ops.add_(add__97, reshape__314)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_90, layer_norm_91, layer_norm_92 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__102, parameter_196, parameter_197, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_84 = paddle.matmul(layer_norm_90, parameter_198, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__103 = paddle._C_ops.add_(matmul_84, parameter_199)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_13 = paddle._C_ops.gelu(add__103, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_85 = paddle.matmul(gelu_13, parameter_200, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__104 = paddle._C_ops.add_(matmul_85, parameter_201)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__105 = paddle._C_ops.add_(add__102, add__104)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_44 = paddle._C_ops.shape(paddle.cast(add__105, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_86 = paddle._C_ops.slice(shape_44, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_93, layer_norm_94, layer_norm_95 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__105, parameter_202, parameter_203, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_81 = [slice_86, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__316, reshape__317 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_93, combine_81), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_45 = paddle._C_ops.shape(paddle.cast(reshape__316, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_87 = paddle._C_ops.slice(shape_45, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_82 = [slice_87, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__318, reshape__319 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__316, combine_82), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_73 = paddle._C_ops.transpose(reshape__318, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__320, reshape__321 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_73, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__322, reshape__323 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__320, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_46 = paddle._C_ops.shape(paddle.cast(reshape__322, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_88 = paddle._C_ops.slice(shape_46, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_86 = paddle.matmul(reshape__322, parameter_204, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__106 = paddle._C_ops.add_(matmul_86, parameter_205)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_83 = [slice_88, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__324, reshape__325 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__106, combine_83), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_74 = paddle._C_ops.transpose(reshape__324, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_89 = paddle._C_ops.slice(transpose_74, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_90 = paddle._C_ops.slice(transpose_74, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_91 = paddle._C_ops.slice(transpose_74, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__14 = paddle._C_ops.scale_(slice_89, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_75 = paddle._C_ops.transpose(slice_90, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_87 = paddle.matmul(scale__14, transpose_75, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__107 = paddle._C_ops.add_(matmul_87, parameter_206)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__14 = paddle._C_ops.softmax_(add__107, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_88 = paddle.matmul(softmax__14, slice_91, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_76 = paddle._C_ops.transpose(matmul_88, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_84 = [slice_88, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__326, reshape__327 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_76, combine_84), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_89 = paddle.matmul(reshape__326, parameter_207, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__108 = paddle._C_ops.add_(matmul_89, parameter_208)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__328, reshape__329 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__108, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__330, reshape__331 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__328, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_77 = paddle._C_ops.transpose(reshape__330, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__332, reshape__333 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_77, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_85 = [slice_86, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__334, reshape__335 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__332, combine_85), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__109 = paddle._C_ops.add_(add__105, reshape__334)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_96, layer_norm_97, layer_norm_98 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__109, parameter_209, parameter_210, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_90 = paddle.matmul(layer_norm_96, parameter_211, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__110 = paddle._C_ops.add_(matmul_90, parameter_212)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_14 = paddle._C_ops.gelu(add__110, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_91 = paddle.matmul(gelu_14, parameter_213, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__111 = paddle._C_ops.add_(matmul_91, parameter_214)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__112 = paddle._C_ops.add_(add__109, add__111)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_47 = paddle._C_ops.shape(paddle.cast(add__112, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_92 = paddle._C_ops.slice(shape_47, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_99, layer_norm_100, layer_norm_101 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__112, parameter_215, parameter_216, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_86 = [slice_92, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__336, reshape__337 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_99, combine_86), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_14 = paddle._C_ops.roll(reshape__336, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_48 = paddle._C_ops.shape(paddle.cast(roll_14, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_93 = paddle._C_ops.slice(shape_48, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_87 = [slice_93, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__338, reshape__339 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_14, combine_87), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_78 = paddle._C_ops.transpose(reshape__338, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__340, reshape__341 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_78, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__342, reshape__343 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__340, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_49 = paddle._C_ops.shape(paddle.cast(reshape__342, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_94 = paddle._C_ops.slice(shape_49, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_92 = paddle.matmul(reshape__342, parameter_217, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__113 = paddle._C_ops.add_(matmul_92, parameter_218)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_88 = [slice_94, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__344, reshape__345 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__113, combine_88), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_79 = paddle._C_ops.transpose(reshape__344, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_95 = paddle._C_ops.slice(transpose_79, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_96 = paddle._C_ops.slice(transpose_79, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_97 = paddle._C_ops.slice(transpose_79, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__15 = paddle._C_ops.scale_(slice_95, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_80 = paddle._C_ops.transpose(slice_96, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_93 = paddle.matmul(scale__15, transpose_80, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__114 = paddle._C_ops.add_(matmul_93, parameter_219)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_7 = paddle._C_ops.memcpy_h2d(slice_94, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__7 = paddle._C_ops.floor_divide_(memcpy_h2d_7, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_89 = [floor_divide__7, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__346, reshape__347 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__114, combine_89), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__115 = paddle._C_ops.add_(reshape__346, parameter_220)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__348, reshape__349 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__115, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__15 = paddle._C_ops.softmax_(reshape__348, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_94 = paddle.matmul(softmax__15, slice_97, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_81 = paddle._C_ops.transpose(matmul_94, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_90 = [slice_94, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__350, reshape__351 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_81, combine_90), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_95 = paddle.matmul(reshape__350, parameter_221, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__116 = paddle._C_ops.add_(matmul_95, parameter_222)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__352, reshape__353 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__116, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__354, reshape__355 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__352, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_82 = paddle._C_ops.transpose(reshape__354, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__356, reshape__357 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_82, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_15 = paddle._C_ops.roll(reshape__356, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_91 = [slice_92, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__358, reshape__359 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_15, combine_91), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__117 = paddle._C_ops.add_(add__112, reshape__358)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_102, layer_norm_103, layer_norm_104 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__117, parameter_223, parameter_224, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_96 = paddle.matmul(layer_norm_102, parameter_225, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__118 = paddle._C_ops.add_(matmul_96, parameter_226)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_15 = paddle._C_ops.gelu(add__118, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_97 = paddle.matmul(gelu_15, parameter_227, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__119 = paddle._C_ops.add_(matmul_97, parameter_228)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__120 = paddle._C_ops.add_(add__117, add__119)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_50 = paddle._C_ops.shape(paddle.cast(add__120, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_98 = paddle._C_ops.slice(shape_50, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_105, layer_norm_106, layer_norm_107 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__120, parameter_229, parameter_230, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_92 = [slice_98, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__360, reshape__361 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_105, combine_92), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_51 = paddle._C_ops.shape(paddle.cast(reshape__360, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_99 = paddle._C_ops.slice(shape_51, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_93 = [slice_99, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__362, reshape__363 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__360, combine_93), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_83 = paddle._C_ops.transpose(reshape__362, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__364, reshape__365 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_83, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__366, reshape__367 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__364, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_52 = paddle._C_ops.shape(paddle.cast(reshape__366, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_100 = paddle._C_ops.slice(shape_52, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_98 = paddle.matmul(reshape__366, parameter_231, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__121 = paddle._C_ops.add_(matmul_98, parameter_232)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_94 = [slice_100, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__368, reshape__369 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__121, combine_94), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_84 = paddle._C_ops.transpose(reshape__368, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_101 = paddle._C_ops.slice(transpose_84, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_102 = paddle._C_ops.slice(transpose_84, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_103 = paddle._C_ops.slice(transpose_84, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__16 = paddle._C_ops.scale_(slice_101, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_85 = paddle._C_ops.transpose(slice_102, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_99 = paddle.matmul(scale__16, transpose_85, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__122 = paddle._C_ops.add_(matmul_99, parameter_233)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__16 = paddle._C_ops.softmax_(add__122, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_100 = paddle.matmul(softmax__16, slice_103, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_86 = paddle._C_ops.transpose(matmul_100, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_95 = [slice_100, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__370, reshape__371 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_86, combine_95), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_101 = paddle.matmul(reshape__370, parameter_234, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__123 = paddle._C_ops.add_(matmul_101, parameter_235)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__372, reshape__373 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__123, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__374, reshape__375 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__372, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_87 = paddle._C_ops.transpose(reshape__374, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__376, reshape__377 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_87, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_96 = [slice_98, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__378, reshape__379 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__376, combine_96), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__124 = paddle._C_ops.add_(add__120, reshape__378)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_108, layer_norm_109, layer_norm_110 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__124, parameter_236, parameter_237, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_102 = paddle.matmul(layer_norm_108, parameter_238, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__125 = paddle._C_ops.add_(matmul_102, parameter_239)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_16 = paddle._C_ops.gelu(add__125, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_103 = paddle.matmul(gelu_16, parameter_240, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__126 = paddle._C_ops.add_(matmul_103, parameter_241)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__127 = paddle._C_ops.add_(add__124, add__126)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_53 = paddle._C_ops.shape(paddle.cast(add__127, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_104 = paddle._C_ops.slice(shape_53, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_111, layer_norm_112, layer_norm_113 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__127, parameter_242, parameter_243, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_97 = [slice_104, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__380, reshape__381 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_111, combine_97), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_16 = paddle._C_ops.roll(reshape__380, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_54 = paddle._C_ops.shape(paddle.cast(roll_16, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_105 = paddle._C_ops.slice(shape_54, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_98 = [slice_105, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__382, reshape__383 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_16, combine_98), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_88 = paddle._C_ops.transpose(reshape__382, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__384, reshape__385 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_88, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__386, reshape__387 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__384, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_55 = paddle._C_ops.shape(paddle.cast(reshape__386, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_106 = paddle._C_ops.slice(shape_55, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_104 = paddle.matmul(reshape__386, parameter_244, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__128 = paddle._C_ops.add_(matmul_104, parameter_245)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_99 = [slice_106, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__388, reshape__389 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__128, combine_99), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_89 = paddle._C_ops.transpose(reshape__388, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_107 = paddle._C_ops.slice(transpose_89, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_108 = paddle._C_ops.slice(transpose_89, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_109 = paddle._C_ops.slice(transpose_89, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__17 = paddle._C_ops.scale_(slice_107, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_90 = paddle._C_ops.transpose(slice_108, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_105 = paddle.matmul(scale__17, transpose_90, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__129 = paddle._C_ops.add_(matmul_105, parameter_246)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_8 = paddle._C_ops.memcpy_h2d(slice_106, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__8 = paddle._C_ops.floor_divide_(memcpy_h2d_8, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_100 = [floor_divide__8, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__390, reshape__391 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__129, combine_100), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__130 = paddle._C_ops.add_(reshape__390, parameter_247)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__392, reshape__393 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__130, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__17 = paddle._C_ops.softmax_(reshape__392, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_106 = paddle.matmul(softmax__17, slice_109, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_91 = paddle._C_ops.transpose(matmul_106, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_101 = [slice_106, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__394, reshape__395 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_91, combine_101), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_107 = paddle.matmul(reshape__394, parameter_248, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__131 = paddle._C_ops.add_(matmul_107, parameter_249)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__396, reshape__397 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__131, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__398, reshape__399 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__396, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_92 = paddle._C_ops.transpose(reshape__398, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__400, reshape__401 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_92, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_17 = paddle._C_ops.roll(reshape__400, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_102 = [slice_104, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__402, reshape__403 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_17, combine_102), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__132 = paddle._C_ops.add_(add__127, reshape__402)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_114, layer_norm_115, layer_norm_116 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__132, parameter_250, parameter_251, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_108 = paddle.matmul(layer_norm_114, parameter_252, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__133 = paddle._C_ops.add_(matmul_108, parameter_253)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_17 = paddle._C_ops.gelu(add__133, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_109 = paddle.matmul(gelu_17, parameter_254, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__134 = paddle._C_ops.add_(matmul_109, parameter_255)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__135 = paddle._C_ops.add_(add__132, add__134)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_56 = paddle._C_ops.shape(paddle.cast(add__135, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_110 = paddle._C_ops.slice(shape_56, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_117, layer_norm_118, layer_norm_119 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__135, parameter_256, parameter_257, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_103 = [slice_110, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__404, reshape__405 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_117, combine_103), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_57 = paddle._C_ops.shape(paddle.cast(reshape__404, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_111 = paddle._C_ops.slice(shape_57, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_104 = [slice_111, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__406, reshape__407 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__404, combine_104), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_93 = paddle._C_ops.transpose(reshape__406, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__408, reshape__409 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_93, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__410, reshape__411 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__408, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_58 = paddle._C_ops.shape(paddle.cast(reshape__410, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_112 = paddle._C_ops.slice(shape_58, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_110 = paddle.matmul(reshape__410, parameter_258, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__136 = paddle._C_ops.add_(matmul_110, parameter_259)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_105 = [slice_112, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__412, reshape__413 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__136, combine_105), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_94 = paddle._C_ops.transpose(reshape__412, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_113 = paddle._C_ops.slice(transpose_94, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_114 = paddle._C_ops.slice(transpose_94, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_115 = paddle._C_ops.slice(transpose_94, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__18 = paddle._C_ops.scale_(slice_113, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_95 = paddle._C_ops.transpose(slice_114, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_111 = paddle.matmul(scale__18, transpose_95, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__137 = paddle._C_ops.add_(matmul_111, parameter_260)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__18 = paddle._C_ops.softmax_(add__137, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_112 = paddle.matmul(softmax__18, slice_115, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_96 = paddle._C_ops.transpose(matmul_112, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_106 = [slice_112, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__414, reshape__415 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_96, combine_106), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_113 = paddle.matmul(reshape__414, parameter_261, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__138 = paddle._C_ops.add_(matmul_113, parameter_262)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__416, reshape__417 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__138, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__418, reshape__419 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__416, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_97 = paddle._C_ops.transpose(reshape__418, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__420, reshape__421 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_97, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_107 = [slice_110, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__422, reshape__423 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__420, combine_107), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__139 = paddle._C_ops.add_(add__135, reshape__422)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_120, layer_norm_121, layer_norm_122 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__139, parameter_263, parameter_264, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_114 = paddle.matmul(layer_norm_120, parameter_265, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__140 = paddle._C_ops.add_(matmul_114, parameter_266)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_18 = paddle._C_ops.gelu(add__140, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_115 = paddle.matmul(gelu_18, parameter_267, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__141 = paddle._C_ops.add_(matmul_115, parameter_268)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__142 = paddle._C_ops.add_(add__139, add__141)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_59 = paddle._C_ops.shape(paddle.cast(add__142, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_116 = paddle._C_ops.slice(shape_59, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_123, layer_norm_124, layer_norm_125 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__142, parameter_269, parameter_270, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_108 = [slice_116, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__424, reshape__425 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_123, combine_108), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_18 = paddle._C_ops.roll(reshape__424, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_60 = paddle._C_ops.shape(paddle.cast(roll_18, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_117 = paddle._C_ops.slice(shape_60, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_109 = [slice_117, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__426, reshape__427 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_18, combine_109), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_98 = paddle._C_ops.transpose(reshape__426, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__428, reshape__429 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_98, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__430, reshape__431 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__428, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_61 = paddle._C_ops.shape(paddle.cast(reshape__430, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_118 = paddle._C_ops.slice(shape_61, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_116 = paddle.matmul(reshape__430, parameter_271, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__143 = paddle._C_ops.add_(matmul_116, parameter_272)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_110 = [slice_118, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__432, reshape__433 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__143, combine_110), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_99 = paddle._C_ops.transpose(reshape__432, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_119 = paddle._C_ops.slice(transpose_99, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_120 = paddle._C_ops.slice(transpose_99, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_121 = paddle._C_ops.slice(transpose_99, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__19 = paddle._C_ops.scale_(slice_119, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_100 = paddle._C_ops.transpose(slice_120, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_117 = paddle.matmul(scale__19, transpose_100, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__144 = paddle._C_ops.add_(matmul_117, parameter_273)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_9 = paddle._C_ops.memcpy_h2d(slice_118, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__9 = paddle._C_ops.floor_divide_(memcpy_h2d_9, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_111 = [floor_divide__9, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__434, reshape__435 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__144, combine_111), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__145 = paddle._C_ops.add_(reshape__434, parameter_274)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__436, reshape__437 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__145, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__19 = paddle._C_ops.softmax_(reshape__436, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_118 = paddle.matmul(softmax__19, slice_121, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_101 = paddle._C_ops.transpose(matmul_118, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_112 = [slice_118, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__438, reshape__439 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_101, combine_112), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_119 = paddle.matmul(reshape__438, parameter_275, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__146 = paddle._C_ops.add_(matmul_119, parameter_276)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__440, reshape__441 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__146, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__442, reshape__443 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__440, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_102 = paddle._C_ops.transpose(reshape__442, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__444, reshape__445 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_102, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_19 = paddle._C_ops.roll(reshape__444, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_113 = [slice_116, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__446, reshape__447 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_19, combine_113), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__147 = paddle._C_ops.add_(add__142, reshape__446)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_126, layer_norm_127, layer_norm_128 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__147, parameter_277, parameter_278, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_120 = paddle.matmul(layer_norm_126, parameter_279, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__148 = paddle._C_ops.add_(matmul_120, parameter_280)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_19 = paddle._C_ops.gelu(add__148, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_121 = paddle.matmul(gelu_19, parameter_281, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__149 = paddle._C_ops.add_(matmul_121, parameter_282)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__150 = paddle._C_ops.add_(add__147, add__149)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_62 = paddle._C_ops.shape(paddle.cast(add__150, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_122 = paddle._C_ops.slice(shape_62, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_129, layer_norm_130, layer_norm_131 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__150, parameter_283, parameter_284, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_114 = [slice_122, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__448, reshape__449 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_129, combine_114), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_63 = paddle._C_ops.shape(paddle.cast(reshape__448, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_123 = paddle._C_ops.slice(shape_63, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_115 = [slice_123, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__450, reshape__451 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__448, combine_115), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_103 = paddle._C_ops.transpose(reshape__450, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__452, reshape__453 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_103, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__454, reshape__455 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__452, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_64 = paddle._C_ops.shape(paddle.cast(reshape__454, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_124 = paddle._C_ops.slice(shape_64, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_122 = paddle.matmul(reshape__454, parameter_285, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__151 = paddle._C_ops.add_(matmul_122, parameter_286)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_116 = [slice_124, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__456, reshape__457 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__151, combine_116), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_104 = paddle._C_ops.transpose(reshape__456, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_125 = paddle._C_ops.slice(transpose_104, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_126 = paddle._C_ops.slice(transpose_104, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_127 = paddle._C_ops.slice(transpose_104, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__20 = paddle._C_ops.scale_(slice_125, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_105 = paddle._C_ops.transpose(slice_126, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_123 = paddle.matmul(scale__20, transpose_105, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__152 = paddle._C_ops.add_(matmul_123, parameter_287)

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__20 = paddle._C_ops.softmax_(add__152, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_124 = paddle.matmul(softmax__20, slice_127, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_106 = paddle._C_ops.transpose(matmul_124, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_117 = [slice_124, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__458, reshape__459 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_106, combine_117), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_125 = paddle.matmul(reshape__458, parameter_288, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__153 = paddle._C_ops.add_(matmul_125, parameter_289)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__460, reshape__461 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__153, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__462, reshape__463 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__460, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_107 = paddle._C_ops.transpose(reshape__462, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__464, reshape__465 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_107, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_118 = [slice_122, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__466, reshape__467 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__464, combine_118), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__154 = paddle._C_ops.add_(add__150, reshape__466)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_132, layer_norm_133, layer_norm_134 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__154, parameter_290, parameter_291, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_126 = paddle.matmul(layer_norm_132, parameter_292, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__155 = paddle._C_ops.add_(matmul_126, parameter_293)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_20 = paddle._C_ops.gelu(add__155, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_127 = paddle.matmul(gelu_20, parameter_294, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__156 = paddle._C_ops.add_(matmul_127, parameter_295)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__157 = paddle._C_ops.add_(add__154, add__156)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_65 = paddle._C_ops.shape(paddle.cast(add__157, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_128 = paddle._C_ops.slice(shape_65, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_135, layer_norm_136, layer_norm_137 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__157, parameter_296, parameter_297, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_119 = [slice_128, constant_33, constant_33, constant_25]

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__468, reshape__469 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_135, combine_119), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_20 = paddle._C_ops.roll(reshape__468, constant_18, [1, 2])

        # pd_op.shape: (4xi32) <- (-1x24x24x512xf16)
        shape_66 = paddle._C_ops.shape(paddle.cast(roll_20, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_129 = paddle._C_ops.slice(shape_66, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_120 = [slice_129, constant_23, constant_5, constant_23, constant_5, constant_25]

        # pd_op.reshape_: (-1x2x12x2x12x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__470, reshape__471 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_20, combine_120), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x2x12x12x512xf16) <- (-1x2x12x2x12x512xf16)
        transpose_108 = paddle._C_ops.transpose(reshape__470, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x2x2x12x12x512xf16) <- (-1x2x2x12x12x512xf16, 4xi64)
        reshape__472, reshape__473 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_108, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 3xi64)
        reshape__474, reshape__475 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__472, constant_37), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x512xf16)
        shape_67 = paddle._C_ops.shape(paddle.cast(reshape__474, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_130 = paddle._C_ops.slice(shape_67, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x1536xf16) <- (-1x144x512xf16, 512x1536xf16)
        matmul_128 = paddle.matmul(reshape__474, parameter_298, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1536xf16) <- (-1x144x1536xf16, 1536xf16)
        add__158 = paddle._C_ops.add_(matmul_128, parameter_299)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_121 = [slice_130, constant_8, constant_9, constant_31, constant_11]

        # pd_op.reshape_: (-1x144x3x16x32xf16, 0x-1x144x1536xf16) <- (-1x144x1536xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__476, reshape__477 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__158, combine_121), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x16x144x32xf16) <- (-1x144x3x16x32xf16)
        transpose_109 = paddle._C_ops.transpose(reshape__476, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_131 = paddle._C_ops.slice(transpose_109, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_132 = paddle._C_ops.slice(transpose_109, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x16x144x32xf16) <- (3x-1x16x144x32xf16, 1xi64, 1xi64)
        slice_133 = paddle._C_ops.slice(transpose_109, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x16x144x32xf16) <- (-1x16x144x32xf16, 1xf32)
        scale__21 = paddle._C_ops.scale_(slice_131, constant_14, float('0'), True)

        # pd_op.transpose: (-1x16x32x144xf16) <- (-1x16x144x32xf16)
        transpose_110 = paddle._C_ops.transpose(slice_132, [0, 1, 3, 2])

        # pd_op.matmul: (-1x16x144x144xf16) <- (-1x16x144x32xf16, -1x16x32x144xf16)
        matmul_129 = paddle.matmul(scale__21, transpose_110, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x16x144x144xf16) <- (-1x16x144x144xf16, 1x16x144x144xf16)
        add__159 = paddle._C_ops.add_(matmul_129, parameter_300)

        # pd_op.memcpy_h2d: (1xi32) <- (1xi32)
        memcpy_h2d_10 = paddle._C_ops.memcpy_h2d(slice_130, 1)

        # pd_op.floor_divide_: (1xi32) <- (1xi32, xi32)
        floor_divide__10 = paddle._C_ops.floor_divide_(memcpy_h2d_10, parameter_84)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_122 = [floor_divide__10, constant_10, constant_31, constant_8, constant_8]

        # pd_op.reshape_: (-1x4x16x144x144xf16, 0x-1x16x144x144xf16) <- (-1x16x144x144xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__478, reshape__479 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__159, combine_122), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 1x4x1x144x144xf16)
        add__160 = paddle._C_ops.add_(reshape__478, parameter_301)

        # pd_op.reshape_: (-1x16x144x144xf16, 0x-1x4x16x144x144xf16) <- (-1x4x16x144x144xf16, 4xi64)
        reshape__480, reshape__481 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__160, constant_40), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.softmax_: (-1x16x144x144xf16) <- (-1x16x144x144xf16)
        softmax__21 = paddle._C_ops.softmax_(reshape__480, -1)

        # pd_op.matmul: (-1x16x144x32xf16) <- (-1x16x144x144xf16, -1x16x144x32xf16)
        matmul_130 = paddle.matmul(softmax__21, slice_133, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x16x32xf16) <- (-1x16x144x32xf16)
        transpose_111 = paddle._C_ops.transpose(matmul_130, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_123 = [slice_130, constant_8, constant_25]

        # pd_op.reshape_: (-1x144x512xf16, 0x-1x144x16x32xf16) <- (-1x144x16x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__482, reshape__483 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_111, combine_123), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x512xf16) <- (-1x144x512xf16, 512x512xf16)
        matmul_131 = paddle.matmul(reshape__482, parameter_302, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x512xf16) <- (-1x144x512xf16, 512xf16)
        add__161 = paddle._C_ops.add_(matmul_131, parameter_303)

        # pd_op.reshape_: (-1x12x12x512xf16, 0x-1x144x512xf16) <- (-1x144x512xf16, 4xi64)
        reshape__484, reshape__485 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__161, constant_36), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x2x2x12x12x512xf16, 0x-1x12x12x512xf16) <- (-1x12x12x512xf16, 6xi64)
        reshape__486, reshape__487 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__484, constant_38), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x2x12x2x12x512xf16) <- (-1x2x2x12x12x512xf16)
        transpose_112 = paddle._C_ops.transpose(reshape__486, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x24x24x512xf16, 0x-1x2x12x2x12x512xf16) <- (-1x2x12x2x12x512xf16, 4xi64)
        reshape__488, reshape__489 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_112, constant_39), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.roll: (-1x24x24x512xf16) <- (-1x24x24x512xf16, 2xi64)
        roll_21 = paddle._C_ops.roll(reshape__488, constant_21, [1, 2])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_124 = [slice_128, constant_34, constant_25]

        # pd_op.reshape_: (-1x576x512xf16, 0x-1x24x24x512xf16) <- (-1x24x24x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__490, reshape__491 = (lambda x, f: f(x))(paddle._C_ops.reshape_(roll_21, combine_124), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__162 = paddle._C_ops.add_(add__157, reshape__490)

        # pd_op.layer_norm: (-1x576x512xf16, -576xf32, -576xf32) <- (-1x576x512xf16, 512xf32, 512xf32)
        layer_norm_138, layer_norm_139, layer_norm_140 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__162, parameter_304, parameter_305, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x576x2048xf16) <- (-1x576x512xf16, 512x2048xf16)
        matmul_132 = paddle.matmul(layer_norm_138, parameter_306, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x2048xf16) <- (-1x576x2048xf16, 2048xf16)
        add__163 = paddle._C_ops.add_(matmul_132, parameter_307)

        # pd_op.gelu: (-1x576x2048xf16) <- (-1x576x2048xf16)
        gelu_21 = paddle._C_ops.gelu(add__163, False)

        # pd_op.matmul: (-1x576x512xf16) <- (-1x576x2048xf16, 2048x512xf16)
        matmul_133 = paddle.matmul(gelu_21, parameter_308, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, 512xf16)
        add__164 = paddle._C_ops.add_(matmul_133, parameter_309)

        # pd_op.add_: (-1x576x512xf16) <- (-1x576x512xf16, -1x576x512xf16)
        add__165 = paddle._C_ops.add_(add__162, add__164)

        # pd_op.shape: (3xi32) <- (-1x576x512xf16)
        shape_68 = paddle._C_ops.shape(paddle.cast(add__165, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_134 = paddle._C_ops.slice(shape_68, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_125 = [slice_134, constant_5, constant_23, constant_5, constant_23, constant_25]

        # pd_op.reshape_: (-1x12x2x12x2x512xf16, 0x-1x576x512xf16) <- (-1x576x512xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__492, reshape__493 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__165, combine_125), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x12x12x2x2x512xf16) <- (-1x12x2x12x2x512xf16)
        transpose_113 = paddle._C_ops.transpose(reshape__492, [0, 1, 3, 4, 2, 5])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_126 = [slice_134, constant_8, constant_41]

        # pd_op.reshape_: (-1x144x2048xf16, 0x-1x12x12x2x2x512xf16) <- (-1x12x12x2x2x512xf16, [1xi32, 1xi32, 1xi32])
        reshape__494, reshape__495 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_113, combine_126), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.layer_norm: (-1x144x2048xf16, -144xf32, -144xf32) <- (-1x144x2048xf16, 2048xf32, 2048xf32)
        layer_norm_141, layer_norm_142, layer_norm_143 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(reshape__494, parameter_310, parameter_311, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x144x1024xf16) <- (-1x144x2048xf16, 2048x1024xf16)
        matmul_134 = paddle.matmul(layer_norm_141, parameter_312, transpose_x=False, transpose_y=False)

        # pd_op.shape: (3xi32) <- (-1x144x1024xf16)
        shape_69 = paddle._C_ops.shape(paddle.cast(matmul_134, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_135 = paddle._C_ops.slice(shape_69, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x144x1024xf16, -144xf32, -144xf32) <- (-1x144x1024xf16, 1024xf32, 1024xf32)
        layer_norm_144, layer_norm_145, layer_norm_146 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(matmul_134, parameter_313, parameter_314, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_127 = [slice_135, constant_5, constant_5, constant_35]

        # pd_op.reshape_: (-1x12x12x1024xf16, 0x-1x144x1024xf16) <- (-1x144x1024xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__496, reshape__497 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_144, combine_127), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x12x12x1024xf16)
        shape_70 = paddle._C_ops.shape(paddle.cast(reshape__496, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_136 = paddle._C_ops.slice(shape_70, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_128 = [slice_136, constant_42, constant_5, constant_42, constant_5, constant_35]

        # pd_op.reshape_: (-1x1x12x1x12x1024xf16, 0x-1x12x12x1024xf16) <- (-1x12x12x1024xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__498, reshape__499 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__496, combine_128), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x1x1x12x12x1024xf16) <- (-1x1x12x1x12x1024xf16)
        transpose_114 = paddle._C_ops.transpose(reshape__498, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x1024xf16, 0x-1x1x1x12x12x1024xf16) <- (-1x1x1x12x12x1024xf16, 4xi64)
        reshape__500, reshape__501 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_114, constant_43), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x1024xf16, 0x-1x12x12x1024xf16) <- (-1x12x12x1024xf16, 3xi64)
        reshape__502, reshape__503 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__500, constant_44), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x1024xf16)
        shape_71 = paddle._C_ops.shape(paddle.cast(reshape__502, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_137 = paddle._C_ops.slice(shape_71, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x3072xf16) <- (-1x144x1024xf16, 1024x3072xf16)
        matmul_135 = paddle.matmul(reshape__502, parameter_315, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x3072xf16) <- (-1x144x3072xf16, 3072xf16)
        add__166 = paddle._C_ops.add_(matmul_135, parameter_316)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_129 = [slice_137, constant_8, constant_9, constant_11, constant_11]

        # pd_op.reshape_: (-1x144x3x32x32xf16, 0x-1x144x3072xf16) <- (-1x144x3072xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__504, reshape__505 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__166, combine_129), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x32x144x32xf16) <- (-1x144x3x32x32xf16)
        transpose_115 = paddle._C_ops.transpose(reshape__504, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x32x144x32xf16) <- (3x-1x32x144x32xf16, 1xi64, 1xi64)
        slice_138 = paddle._C_ops.slice(transpose_115, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x32x144x32xf16) <- (3x-1x32x144x32xf16, 1xi64, 1xi64)
        slice_139 = paddle._C_ops.slice(transpose_115, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x32x144x32xf16) <- (3x-1x32x144x32xf16, 1xi64, 1xi64)
        slice_140 = paddle._C_ops.slice(transpose_115, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x32x144x32xf16) <- (-1x32x144x32xf16, 1xf32)
        scale__22 = paddle._C_ops.scale_(slice_138, constant_14, float('0'), True)

        # pd_op.transpose: (-1x32x32x144xf16) <- (-1x32x144x32xf16)
        transpose_116 = paddle._C_ops.transpose(slice_139, [0, 1, 3, 2])

        # pd_op.matmul: (-1x32x144x144xf16) <- (-1x32x144x32xf16, -1x32x32x144xf16)
        matmul_136 = paddle.matmul(scale__22, transpose_116, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x32x144x144xf16) <- (-1x32x144x144xf16, 1x32x144x144xf16)
        add__167 = paddle._C_ops.add_(matmul_136, parameter_317)

        # pd_op.softmax_: (-1x32x144x144xf16) <- (-1x32x144x144xf16)
        softmax__22 = paddle._C_ops.softmax_(add__167, -1)

        # pd_op.matmul: (-1x32x144x32xf16) <- (-1x32x144x144xf16, -1x32x144x32xf16)
        matmul_137 = paddle.matmul(softmax__22, slice_140, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x32x32xf16) <- (-1x32x144x32xf16)
        transpose_117 = paddle._C_ops.transpose(matmul_137, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_130 = [slice_137, constant_8, constant_35]

        # pd_op.reshape_: (-1x144x1024xf16, 0x-1x144x32x32xf16) <- (-1x144x32x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__506, reshape__507 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_117, combine_130), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x1024xf16) <- (-1x144x1024xf16, 1024x1024xf16)
        matmul_138 = paddle.matmul(reshape__506, parameter_318, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1024xf16) <- (-1x144x1024xf16, 1024xf16)
        add__168 = paddle._C_ops.add_(matmul_138, parameter_319)

        # pd_op.reshape_: (-1x12x12x1024xf16, 0x-1x144x1024xf16) <- (-1x144x1024xf16, 4xi64)
        reshape__508, reshape__509 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__168, constant_43), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x1x1x12x12x1024xf16, 0x-1x12x12x1024xf16) <- (-1x12x12x1024xf16, 6xi64)
        reshape__510, reshape__511 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__508, constant_45), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x1x12x1x12x1024xf16) <- (-1x1x1x12x12x1024xf16)
        transpose_118 = paddle._C_ops.transpose(reshape__510, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x1024xf16, 0x-1x1x12x1x12x1024xf16) <- (-1x1x12x1x12x1024xf16, 4xi64)
        reshape__512, reshape__513 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_118, constant_43), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_131 = [slice_135, constant_8, constant_35]

        # pd_op.reshape_: (-1x144x1024xf16, 0x-1x12x12x1024xf16) <- (-1x12x12x1024xf16, [1xi32, 1xi32, 1xi32])
        reshape__514, reshape__515 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__512, combine_131), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x144x1024xf16) <- (-1x144x1024xf16, -1x144x1024xf16)
        add__169 = paddle._C_ops.add_(matmul_134, reshape__514)

        # pd_op.layer_norm: (-1x144x1024xf16, -144xf32, -144xf32) <- (-1x144x1024xf16, 1024xf32, 1024xf32)
        layer_norm_147, layer_norm_148, layer_norm_149 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__169, parameter_320, parameter_321, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x144x4096xf16) <- (-1x144x1024xf16, 1024x4096xf16)
        matmul_139 = paddle.matmul(layer_norm_147, parameter_322, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x4096xf16) <- (-1x144x4096xf16, 4096xf16)
        add__170 = paddle._C_ops.add_(matmul_139, parameter_323)

        # pd_op.gelu: (-1x144x4096xf16) <- (-1x144x4096xf16)
        gelu_22 = paddle._C_ops.gelu(add__170, False)

        # pd_op.matmul: (-1x144x1024xf16) <- (-1x144x4096xf16, 4096x1024xf16)
        matmul_140 = paddle.matmul(gelu_22, parameter_324, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1024xf16) <- (-1x144x1024xf16, 1024xf16)
        add__171 = paddle._C_ops.add_(matmul_140, parameter_325)

        # pd_op.add_: (-1x144x1024xf16) <- (-1x144x1024xf16, -1x144x1024xf16)
        add__172 = paddle._C_ops.add_(add__169, add__171)

        # pd_op.shape: (3xi32) <- (-1x144x1024xf16)
        shape_72 = paddle._C_ops.shape(paddle.cast(add__172, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_141 = paddle._C_ops.slice(shape_72, [0], constant_0, constant_1, [1], [0])

        # pd_op.layer_norm: (-1x144x1024xf16, -144xf32, -144xf32) <- (-1x144x1024xf16, 1024xf32, 1024xf32)
        layer_norm_150, layer_norm_151, layer_norm_152 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__172, parameter_326, parameter_327, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32)
        combine_132 = [slice_141, constant_5, constant_5, constant_35]

        # pd_op.reshape_: (-1x12x12x1024xf16, 0x-1x144x1024xf16) <- (-1x144x1024xf16, [1xi32, 1xi32, 1xi32, 1xi32])
        reshape__516, reshape__517 = (lambda x, f: f(x))(paddle._C_ops.reshape_(layer_norm_150, combine_132), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (4xi32) <- (-1x12x12x1024xf16)
        shape_73 = paddle._C_ops.shape(paddle.cast(reshape__516, 'float32'))

        # pd_op.slice: (1xi32) <- (4xi32, 1xi64, 1xi64)
        slice_142 = paddle._C_ops.slice(shape_73, [0], constant_0, constant_1, [1], [0])

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_133 = [slice_142, constant_42, constant_5, constant_42, constant_5, constant_35]

        # pd_op.reshape_: (-1x1x12x1x12x1024xf16, 0x-1x12x12x1024xf16) <- (-1x12x12x1024xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__518, reshape__519 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__516, combine_133), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x1x1x12x12x1024xf16) <- (-1x1x12x1x12x1024xf16)
        transpose_119 = paddle._C_ops.transpose(reshape__518, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x1024xf16, 0x-1x1x1x12x12x1024xf16) <- (-1x1x1x12x12x1024xf16, 4xi64)
        reshape__520, reshape__521 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_119, constant_43), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x144x1024xf16, 0x-1x12x12x1024xf16) <- (-1x12x12x1024xf16, 3xi64)
        reshape__522, reshape__523 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__520, constant_44), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.shape: (3xi32) <- (-1x144x1024xf16)
        shape_74 = paddle._C_ops.shape(paddle.cast(reshape__522, 'float32'))

        # pd_op.slice: (1xi32) <- (3xi32, 1xi64, 1xi64)
        slice_143 = paddle._C_ops.slice(shape_74, [0], constant_0, constant_1, [1], [0])

        # pd_op.matmul: (-1x144x3072xf16) <- (-1x144x1024xf16, 1024x3072xf16)
        matmul_141 = paddle.matmul(reshape__522, parameter_328, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x3072xf16) <- (-1x144x3072xf16, 3072xf16)
        add__173 = paddle._C_ops.add_(matmul_141, parameter_329)

        # builtin.combine: ([1xi32, 1xi32, 1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32, 1xi32, 1xi32)
        combine_134 = [slice_143, constant_8, constant_9, constant_11, constant_11]

        # pd_op.reshape_: (-1x144x3x32x32xf16, 0x-1x144x3072xf16) <- (-1x144x3072xf16, [1xi32, 1xi32, 1xi32, 1xi32, 1xi32])
        reshape__524, reshape__525 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__173, combine_134), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (3x-1x32x144x32xf16) <- (-1x144x3x32x32xf16)
        transpose_120 = paddle._C_ops.transpose(reshape__524, [2, 0, 3, 1, 4])

        # pd_op.slice: (-1x32x144x32xf16) <- (3x-1x32x144x32xf16, 1xi64, 1xi64)
        slice_144 = paddle._C_ops.slice(transpose_120, [0], constant_0, constant_1, [1], [0])

        # pd_op.slice: (-1x32x144x32xf16) <- (3x-1x32x144x32xf16, 1xi64, 1xi64)
        slice_145 = paddle._C_ops.slice(transpose_120, [0], constant_1, constant_12, [1], [0])

        # pd_op.slice: (-1x32x144x32xf16) <- (3x-1x32x144x32xf16, 1xi64, 1xi64)
        slice_146 = paddle._C_ops.slice(transpose_120, [0], constant_12, constant_13, [1], [0])

        # pd_op.scale_: (-1x32x144x32xf16) <- (-1x32x144x32xf16, 1xf32)
        scale__23 = paddle._C_ops.scale_(slice_144, constant_14, float('0'), True)

        # pd_op.transpose: (-1x32x32x144xf16) <- (-1x32x144x32xf16)
        transpose_121 = paddle._C_ops.transpose(slice_145, [0, 1, 3, 2])

        # pd_op.matmul: (-1x32x144x144xf16) <- (-1x32x144x32xf16, -1x32x32x144xf16)
        matmul_142 = paddle.matmul(scale__23, transpose_121, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x32x144x144xf16) <- (-1x32x144x144xf16, 1x32x144x144xf16)
        add__174 = paddle._C_ops.add_(matmul_142, parameter_330)

        # pd_op.softmax_: (-1x32x144x144xf16) <- (-1x32x144x144xf16)
        softmax__23 = paddle._C_ops.softmax_(add__174, -1)

        # pd_op.matmul: (-1x32x144x32xf16) <- (-1x32x144x144xf16, -1x32x144x32xf16)
        matmul_143 = paddle.matmul(softmax__23, slice_146, transpose_x=False, transpose_y=False)

        # pd_op.transpose: (-1x144x32x32xf16) <- (-1x32x144x32xf16)
        transpose_122 = paddle._C_ops.transpose(matmul_143, [0, 2, 1, 3])

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_135 = [slice_143, constant_8, constant_35]

        # pd_op.reshape_: (-1x144x1024xf16, 0x-1x144x32x32xf16) <- (-1x144x32x32xf16, [1xi32, 1xi32, 1xi32])
        reshape__526, reshape__527 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_122, combine_135), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x144x1024xf16) <- (-1x144x1024xf16, 1024x1024xf16)
        matmul_144 = paddle.matmul(reshape__526, parameter_331, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1024xf16) <- (-1x144x1024xf16, 1024xf16)
        add__175 = paddle._C_ops.add_(matmul_144, parameter_332)

        # pd_op.reshape_: (-1x12x12x1024xf16, 0x-1x144x1024xf16) <- (-1x144x1024xf16, 4xi64)
        reshape__528, reshape__529 = (lambda x, f: f(x))(paddle._C_ops.reshape_(add__175, constant_43), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.reshape_: (-1x1x1x12x12x1024xf16, 0x-1x12x12x1024xf16) <- (-1x12x12x1024xf16, 6xi64)
        reshape__530, reshape__531 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__528, constant_45), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.transpose: (-1x1x12x1x12x1024xf16) <- (-1x1x1x12x12x1024xf16)
        transpose_123 = paddle._C_ops.transpose(reshape__530, [0, 1, 3, 2, 4, 5])

        # pd_op.reshape_: (-1x12x12x1024xf16, 0x-1x1x12x1x12x1024xf16) <- (-1x1x12x1x12x1024xf16, 4xi64)
        reshape__532, reshape__533 = (lambda x, f: f(x))(paddle._C_ops.reshape_(transpose_123, constant_43), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # builtin.combine: ([1xi32, 1xi32, 1xi32]) <- (1xi32, 1xi32, 1xi32)
        combine_136 = [slice_141, constant_8, constant_35]

        # pd_op.reshape_: (-1x144x1024xf16, 0x-1x12x12x1024xf16) <- (-1x12x12x1024xf16, [1xi32, 1xi32, 1xi32])
        reshape__534, reshape__535 = (lambda x, f: f(x))(paddle._C_ops.reshape_(reshape__532, combine_136), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.add_: (-1x144x1024xf16) <- (-1x144x1024xf16, -1x144x1024xf16)
        add__176 = paddle._C_ops.add_(add__172, reshape__534)

        # pd_op.layer_norm: (-1x144x1024xf16, -144xf32, -144xf32) <- (-1x144x1024xf16, 1024xf32, 1024xf32)
        layer_norm_153, layer_norm_154, layer_norm_155 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__176, parameter_333, parameter_334, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.matmul: (-1x144x4096xf16) <- (-1x144x1024xf16, 1024x4096xf16)
        matmul_145 = paddle.matmul(layer_norm_153, parameter_335, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x4096xf16) <- (-1x144x4096xf16, 4096xf16)
        add__177 = paddle._C_ops.add_(matmul_145, parameter_336)

        # pd_op.gelu: (-1x144x4096xf16) <- (-1x144x4096xf16)
        gelu_23 = paddle._C_ops.gelu(add__177, False)

        # pd_op.matmul: (-1x144x1024xf16) <- (-1x144x4096xf16, 4096x1024xf16)
        matmul_146 = paddle.matmul(gelu_23, parameter_337, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x144x1024xf16) <- (-1x144x1024xf16, 1024xf16)
        add__178 = paddle._C_ops.add_(matmul_146, parameter_338)

        # pd_op.add_: (-1x144x1024xf16) <- (-1x144x1024xf16, -1x144x1024xf16)
        add__179 = paddle._C_ops.add_(add__176, add__178)

        # pd_op.layer_norm: (-1x144x1024xf16, -144xf32, -144xf32) <- (-1x144x1024xf16, 1024xf32, 1024xf32)
        layer_norm_156, layer_norm_157, layer_norm_158 = (lambda x, f: f(x))(paddle._C_ops.layer_norm(add__179, parameter_339, parameter_340, float('1e-05'), 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None,None))

        # pd_op.transpose: (-1x1024x144xf16) <- (-1x144x1024xf16)
        transpose_124 = paddle._C_ops.transpose(layer_norm_156, [0, 2, 1])

        # pd_op.unsqueeze_: (-1x1024x1x144xf16, None) <- (-1x1024x144xf16, 1xi64)
        unsqueeze__0, unsqueeze__1 = (lambda x, f: f(x))(paddle._C_ops.unsqueeze_(transpose_124, constant_12), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.pool2d: (-1x1024x1x1xf16) <- (-1x1024x1x144xf16, 2xi64)
        pool2d_0 = paddle._C_ops.pool2d(unsqueeze__0, constant_46, [1, 1], [0, 0], False, True, 'NCHW', 'avg', False, True, 'EXPLICIT')

        # pd_op.squeeze_: (-1x1024x1xf16, None) <- (-1x1024x1x1xf16, 1xi64)
        squeeze__0, squeeze__1 = (lambda x, f: f(x))(paddle._C_ops.squeeze_(pool2d_0, constant_12), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.flatten_: (-1x1024xf16, None) <- (-1x1024x1xf16)
        flatten__2, flatten__3 = (lambda x, f: f(x))(paddle._C_ops.flatten_(squeeze__0, 1, 2), lambda out: out if isinstance(out, (list, tuple)) else (out, None))

        # pd_op.matmul: (-1x1000xf16) <- (-1x1024xf16, 1024x1000xf16)
        matmul_147 = paddle.matmul(flatten__2, parameter_341, transpose_x=False, transpose_y=False)

        # pd_op.add_: (-1x1000xf16) <- (-1x1000xf16, 1000xf16)
        add__180 = paddle._C_ops.add_(matmul_147, parameter_342)

        # pd_op.softmax_: (-1x1000xf16) <- (-1x1000xf16)
        softmax__24 = paddle._C_ops.softmax_(add__180, -1)

        # pd_op.cast: (-1x1000xf32) <- (-1x1000xf16)
        cast_1 = paddle._C_ops.cast(softmax__24, paddle.float32)
        return cast_1



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


class CinnTestBase:
    def setUp(self):
        paddle.seed(2024)
        self.prepare_data()

    def _test_entry(self):
        dy_outs = self.entry(use_cinn=False)
        cinn_outs = self.entry(use_cinn=GetEnvVarEnableCinn())

        for cinn_out, dy_out in zip(cinn_outs, dy_outs):
          if type(cinn_out) is list and type(dy_out) is list:
            for x, y in zip(cinn_out, dy_out):
              self.assert_all_close(x, y)
          else:
            self.assert_all_close(cinn_out, dy_out)

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

class ModuleOp(paddle.nn.Layer, BlockEntries):
    def __init__(self):
        super().__init__()

    def forward(self, constant_46, constant_45, constant_44, constant_43, constant_42, constant_41, parameter_301, parameter_274, parameter_247, parameter_220, parameter_193, parameter_166, parameter_139, parameter_112, constant_40, parameter_85, parameter_84, constant_39, constant_38, constant_37, constant_36, constant_35, constant_34, constant_33, constant_32, parameter_54, constant_31, parameter_53, constant_30, constant_29, constant_28, constant_27, constant_26, constant_25, constant_24, constant_23, constant_22, constant_21, constant_20, parameter_23, constant_19, parameter_22, constant_18, constant_17, constant_16, constant_15, constant_14, constant_13, constant_12, constant_11, constant_10, constant_9, constant_8, constant_7, constant_6, constant_5, constant_4, constant_3, constant_2, constant_1, constant_0, parameter_1, parameter_0, parameter_3, parameter_2, parameter_5, parameter_4, parameter_6, parameter_7, parameter_8, parameter_9, parameter_10, parameter_12, parameter_11, parameter_13, parameter_14, parameter_15, parameter_16, parameter_18, parameter_17, parameter_19, parameter_20, parameter_21, parameter_24, parameter_25, parameter_27, parameter_26, parameter_28, parameter_29, parameter_30, parameter_31, parameter_33, parameter_32, parameter_34, parameter_36, parameter_35, parameter_37, parameter_38, parameter_39, parameter_40, parameter_41, parameter_43, parameter_42, parameter_44, parameter_45, parameter_46, parameter_47, parameter_49, parameter_48, parameter_50, parameter_51, parameter_52, parameter_55, parameter_56, parameter_58, parameter_57, parameter_59, parameter_60, parameter_61, parameter_62, parameter_64, parameter_63, parameter_65, parameter_67, parameter_66, parameter_68, parameter_69, parameter_70, parameter_71, parameter_72, parameter_74, parameter_73, parameter_75, parameter_76, parameter_77, parameter_78, parameter_80, parameter_79, parameter_81, parameter_82, parameter_83, parameter_86, parameter_87, parameter_89, parameter_88, parameter_90, parameter_91, parameter_92, parameter_93, parameter_95, parameter_94, parameter_96, parameter_97, parameter_98, parameter_99, parameter_100, parameter_102, parameter_101, parameter_103, parameter_104, parameter_105, parameter_106, parameter_108, parameter_107, parameter_109, parameter_110, parameter_111, parameter_113, parameter_114, parameter_116, parameter_115, parameter_117, parameter_118, parameter_119, parameter_120, parameter_122, parameter_121, parameter_123, parameter_124, parameter_125, parameter_126, parameter_127, parameter_129, parameter_128, parameter_130, parameter_131, parameter_132, parameter_133, parameter_135, parameter_134, parameter_136, parameter_137, parameter_138, parameter_140, parameter_141, parameter_143, parameter_142, parameter_144, parameter_145, parameter_146, parameter_147, parameter_149, parameter_148, parameter_150, parameter_151, parameter_152, parameter_153, parameter_154, parameter_156, parameter_155, parameter_157, parameter_158, parameter_159, parameter_160, parameter_162, parameter_161, parameter_163, parameter_164, parameter_165, parameter_167, parameter_168, parameter_170, parameter_169, parameter_171, parameter_172, parameter_173, parameter_174, parameter_176, parameter_175, parameter_177, parameter_178, parameter_179, parameter_180, parameter_181, parameter_183, parameter_182, parameter_184, parameter_185, parameter_186, parameter_187, parameter_189, parameter_188, parameter_190, parameter_191, parameter_192, parameter_194, parameter_195, parameter_197, parameter_196, parameter_198, parameter_199, parameter_200, parameter_201, parameter_203, parameter_202, parameter_204, parameter_205, parameter_206, parameter_207, parameter_208, parameter_210, parameter_209, parameter_211, parameter_212, parameter_213, parameter_214, parameter_216, parameter_215, parameter_217, parameter_218, parameter_219, parameter_221, parameter_222, parameter_224, parameter_223, parameter_225, parameter_226, parameter_227, parameter_228, parameter_230, parameter_229, parameter_231, parameter_232, parameter_233, parameter_234, parameter_235, parameter_237, parameter_236, parameter_238, parameter_239, parameter_240, parameter_241, parameter_243, parameter_242, parameter_244, parameter_245, parameter_246, parameter_248, parameter_249, parameter_251, parameter_250, parameter_252, parameter_253, parameter_254, parameter_255, parameter_257, parameter_256, parameter_258, parameter_259, parameter_260, parameter_261, parameter_262, parameter_264, parameter_263, parameter_265, parameter_266, parameter_267, parameter_268, parameter_270, parameter_269, parameter_271, parameter_272, parameter_273, parameter_275, parameter_276, parameter_278, parameter_277, parameter_279, parameter_280, parameter_281, parameter_282, parameter_284, parameter_283, parameter_285, parameter_286, parameter_287, parameter_288, parameter_289, parameter_291, parameter_290, parameter_292, parameter_293, parameter_294, parameter_295, parameter_297, parameter_296, parameter_298, parameter_299, parameter_300, parameter_302, parameter_303, parameter_305, parameter_304, parameter_306, parameter_307, parameter_308, parameter_309, parameter_311, parameter_310, parameter_312, parameter_314, parameter_313, parameter_315, parameter_316, parameter_317, parameter_318, parameter_319, parameter_321, parameter_320, parameter_322, parameter_323, parameter_324, parameter_325, parameter_327, parameter_326, parameter_328, parameter_329, parameter_330, parameter_331, parameter_332, parameter_334, parameter_333, parameter_335, parameter_336, parameter_337, parameter_338, parameter_340, parameter_339, parameter_341, parameter_342, feed_0):
        return self.builtin_module_3188_0_0(constant_46, constant_45, constant_44, constant_43, constant_42, constant_41, parameter_301, parameter_274, parameter_247, parameter_220, parameter_193, parameter_166, parameter_139, parameter_112, constant_40, parameter_85, parameter_84, constant_39, constant_38, constant_37, constant_36, constant_35, constant_34, constant_33, constant_32, parameter_54, constant_31, parameter_53, constant_30, constant_29, constant_28, constant_27, constant_26, constant_25, constant_24, constant_23, constant_22, constant_21, constant_20, parameter_23, constant_19, parameter_22, constant_18, constant_17, constant_16, constant_15, constant_14, constant_13, constant_12, constant_11, constant_10, constant_9, constant_8, constant_7, constant_6, constant_5, constant_4, constant_3, constant_2, constant_1, constant_0, parameter_1, parameter_0, parameter_3, parameter_2, parameter_5, parameter_4, parameter_6, parameter_7, parameter_8, parameter_9, parameter_10, parameter_12, parameter_11, parameter_13, parameter_14, parameter_15, parameter_16, parameter_18, parameter_17, parameter_19, parameter_20, parameter_21, parameter_24, parameter_25, parameter_27, parameter_26, parameter_28, parameter_29, parameter_30, parameter_31, parameter_33, parameter_32, parameter_34, parameter_36, parameter_35, parameter_37, parameter_38, parameter_39, parameter_40, parameter_41, parameter_43, parameter_42, parameter_44, parameter_45, parameter_46, parameter_47, parameter_49, parameter_48, parameter_50, parameter_51, parameter_52, parameter_55, parameter_56, parameter_58, parameter_57, parameter_59, parameter_60, parameter_61, parameter_62, parameter_64, parameter_63, parameter_65, parameter_67, parameter_66, parameter_68, parameter_69, parameter_70, parameter_71, parameter_72, parameter_74, parameter_73, parameter_75, parameter_76, parameter_77, parameter_78, parameter_80, parameter_79, parameter_81, parameter_82, parameter_83, parameter_86, parameter_87, parameter_89, parameter_88, parameter_90, parameter_91, parameter_92, parameter_93, parameter_95, parameter_94, parameter_96, parameter_97, parameter_98, parameter_99, parameter_100, parameter_102, parameter_101, parameter_103, parameter_104, parameter_105, parameter_106, parameter_108, parameter_107, parameter_109, parameter_110, parameter_111, parameter_113, parameter_114, parameter_116, parameter_115, parameter_117, parameter_118, parameter_119, parameter_120, parameter_122, parameter_121, parameter_123, parameter_124, parameter_125, parameter_126, parameter_127, parameter_129, parameter_128, parameter_130, parameter_131, parameter_132, parameter_133, parameter_135, parameter_134, parameter_136, parameter_137, parameter_138, parameter_140, parameter_141, parameter_143, parameter_142, parameter_144, parameter_145, parameter_146, parameter_147, parameter_149, parameter_148, parameter_150, parameter_151, parameter_152, parameter_153, parameter_154, parameter_156, parameter_155, parameter_157, parameter_158, parameter_159, parameter_160, parameter_162, parameter_161, parameter_163, parameter_164, parameter_165, parameter_167, parameter_168, parameter_170, parameter_169, parameter_171, parameter_172, parameter_173, parameter_174, parameter_176, parameter_175, parameter_177, parameter_178, parameter_179, parameter_180, parameter_181, parameter_183, parameter_182, parameter_184, parameter_185, parameter_186, parameter_187, parameter_189, parameter_188, parameter_190, parameter_191, parameter_192, parameter_194, parameter_195, parameter_197, parameter_196, parameter_198, parameter_199, parameter_200, parameter_201, parameter_203, parameter_202, parameter_204, parameter_205, parameter_206, parameter_207, parameter_208, parameter_210, parameter_209, parameter_211, parameter_212, parameter_213, parameter_214, parameter_216, parameter_215, parameter_217, parameter_218, parameter_219, parameter_221, parameter_222, parameter_224, parameter_223, parameter_225, parameter_226, parameter_227, parameter_228, parameter_230, parameter_229, parameter_231, parameter_232, parameter_233, parameter_234, parameter_235, parameter_237, parameter_236, parameter_238, parameter_239, parameter_240, parameter_241, parameter_243, parameter_242, parameter_244, parameter_245, parameter_246, parameter_248, parameter_249, parameter_251, parameter_250, parameter_252, parameter_253, parameter_254, parameter_255, parameter_257, parameter_256, parameter_258, parameter_259, parameter_260, parameter_261, parameter_262, parameter_264, parameter_263, parameter_265, parameter_266, parameter_267, parameter_268, parameter_270, parameter_269, parameter_271, parameter_272, parameter_273, parameter_275, parameter_276, parameter_278, parameter_277, parameter_279, parameter_280, parameter_281, parameter_282, parameter_284, parameter_283, parameter_285, parameter_286, parameter_287, parameter_288, parameter_289, parameter_291, parameter_290, parameter_292, parameter_293, parameter_294, parameter_295, parameter_297, parameter_296, parameter_298, parameter_299, parameter_300, parameter_302, parameter_303, parameter_305, parameter_304, parameter_306, parameter_307, parameter_308, parameter_309, parameter_311, parameter_310, parameter_312, parameter_314, parameter_313, parameter_315, parameter_316, parameter_317, parameter_318, parameter_319, parameter_321, parameter_320, parameter_322, parameter_323, parameter_324, parameter_325, parameter_327, parameter_326, parameter_328, parameter_329, parameter_330, parameter_331, parameter_332, parameter_334, parameter_333, parameter_335, parameter_336, parameter_337, parameter_338, parameter_340, parameter_339, parameter_341, parameter_342, feed_0)

@unittest.skipIf(need_skip, skip_message)
class Test_builtin_module_3188_0_0(CinnTestBase, unittest.TestCase):
    def prepare_data(self):
        self.inputs = [
            # constant_46
            paddle.to_tensor([1, 1], dtype='int64').reshape([2]),
            # constant_45
            paddle.to_tensor([-1, 1, 1, 12, 12, 1024], dtype='int64').reshape([6]),
            # constant_44
            paddle.to_tensor([-1, 144, 1024], dtype='int64').reshape([3]),
            # constant_43
            paddle.to_tensor([-1, 12, 12, 1024], dtype='int64').reshape([4]),
            # constant_42
            paddle.to_tensor([1], dtype='int32').reshape([1]),
            # constant_41
            paddle.to_tensor([2048], dtype='int32').reshape([1]),
            # parameter_301
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_274
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_247
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_220
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_193
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_166
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_139
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_112
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # constant_40
            paddle.to_tensor([-1, 16, 144, 144], dtype='int64').reshape([4]),
            # parameter_85
            paddle.uniform([1, 4, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_84
            paddle.to_tensor([4], dtype='int32').reshape([]),
            # constant_39
            paddle.to_tensor([-1, 24, 24, 512], dtype='int64').reshape([4]),
            # constant_38
            paddle.to_tensor([-1, 2, 2, 12, 12, 512], dtype='int64').reshape([6]),
            # constant_37
            paddle.to_tensor([-1, 144, 512], dtype='int64').reshape([3]),
            # constant_36
            paddle.to_tensor([-1, 12, 12, 512], dtype='int64').reshape([4]),
            # constant_35
            paddle.to_tensor([1024], dtype='int32').reshape([1]),
            # constant_34
            paddle.to_tensor([576], dtype='int32').reshape([1]),
            # constant_33
            paddle.to_tensor([24], dtype='int32').reshape([1]),
            # constant_32
            paddle.to_tensor([-1, 8, 144, 144], dtype='int64').reshape([4]),
            # parameter_54
            paddle.uniform([1, 16, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # constant_31
            paddle.to_tensor([16], dtype='int32').reshape([1]),
            # parameter_53
            paddle.to_tensor([16], dtype='int32').reshape([]),
            # constant_30
            paddle.to_tensor([-1, 48, 48, 256], dtype='int64').reshape([4]),
            # constant_29
            paddle.to_tensor([-1, 4, 4, 12, 12, 256], dtype='int64').reshape([6]),
            # constant_28
            paddle.to_tensor([-1, 144, 256], dtype='int64').reshape([3]),
            # constant_27
            paddle.to_tensor([-1, 12, 12, 256], dtype='int64').reshape([4]),
            # constant_26
            paddle.to_tensor([256], dtype='int32').reshape([1]),
            # constant_25
            paddle.to_tensor([512], dtype='int32').reshape([1]),
            # constant_24
            paddle.to_tensor([2304], dtype='int32').reshape([1]),
            # constant_23
            paddle.to_tensor([2], dtype='int32').reshape([1]),
            # constant_22
            paddle.to_tensor([48], dtype='int32').reshape([1]),
            # constant_21
            paddle.to_tensor([6, 6], dtype='int64').reshape([2]),
            # constant_20
            paddle.to_tensor([-1, 4, 144, 144], dtype='int64').reshape([4]),
            # parameter_23
            paddle.uniform([1, 64, 1, 144, 144], dtype='float16', min=0, max=0.5),
            # constant_19
            paddle.to_tensor([64], dtype='int32').reshape([1]),
            # parameter_22
            paddle.to_tensor([64], dtype='int32').reshape([]),
            # constant_18
            paddle.to_tensor([-6, -6], dtype='int64').reshape([2]),
            # constant_17
            paddle.to_tensor([9216], dtype='int32').reshape([1]),
            # constant_16
            paddle.to_tensor([-1, 96, 96, 128], dtype='int64').reshape([4]),
            # constant_15
            paddle.to_tensor([-1, 8, 8, 12, 12, 128], dtype='int64').reshape([6]),
            # constant_14
            paddle.uniform([1], dtype='float32', min=0, max=0.5),
            # constant_13
            paddle.to_tensor([3], dtype='int64').reshape([1]),
            # constant_12
            paddle.to_tensor([2], dtype='int64').reshape([1]),
            # constant_11
            paddle.to_tensor([32], dtype='int32').reshape([1]),
            # constant_10
            paddle.to_tensor([4], dtype='int32').reshape([1]),
            # constant_9
            paddle.to_tensor([3], dtype='int32').reshape([1]),
            # constant_8
            paddle.to_tensor([144], dtype='int32').reshape([1]),
            # constant_7
            paddle.to_tensor([-1, 144, 128], dtype='int64').reshape([3]),
            # constant_6
            paddle.to_tensor([-1, 12, 12, 128], dtype='int64').reshape([4]),
            # constant_5
            paddle.to_tensor([12], dtype='int32').reshape([1]),
            # constant_4
            paddle.to_tensor([8], dtype='int32').reshape([1]),
            # constant_3
            paddle.to_tensor([128], dtype='int32').reshape([1]),
            # constant_2
            paddle.to_tensor([96], dtype='int32').reshape([1]),
            # constant_1
            paddle.to_tensor([1], dtype='int64').reshape([1]),
            # constant_0
            paddle.to_tensor([0], dtype='int64').reshape([1]),
            # parameter_1
            paddle.uniform([1, 128, 1, 1], dtype='float16', min=0, max=0.5),
            # parameter_0
            paddle.uniform([128, 3, 4, 4], dtype='float16', min=0, max=0.5),
            # parameter_3
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_2
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_5
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_4
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_6
            paddle.uniform([128, 384], dtype='float16', min=0, max=0.5),
            # parameter_7
            paddle.uniform([384], dtype='float16', min=0, max=0.5),
            # parameter_8
            paddle.uniform([1, 4, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_9
            paddle.uniform([128, 128], dtype='float16', min=0, max=0.5),
            # parameter_10
            paddle.uniform([128], dtype='float16', min=0, max=0.5),
            # parameter_12
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_11
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_13
            paddle.uniform([128, 512], dtype='float16', min=0, max=0.5),
            # parameter_14
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_15
            paddle.uniform([512, 128], dtype='float16', min=0, max=0.5),
            # parameter_16
            paddle.uniform([128], dtype='float16', min=0, max=0.5),
            # parameter_18
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_17
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_19
            paddle.uniform([128, 384], dtype='float16', min=0, max=0.5),
            # parameter_20
            paddle.uniform([384], dtype='float16', min=0, max=0.5),
            # parameter_21
            paddle.uniform([1, 4, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_24
            paddle.uniform([128, 128], dtype='float16', min=0, max=0.5),
            # parameter_25
            paddle.uniform([128], dtype='float16', min=0, max=0.5),
            # parameter_27
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_26
            paddle.uniform([128], dtype='float32', min=0, max=0.5),
            # parameter_28
            paddle.uniform([128, 512], dtype='float16', min=0, max=0.5),
            # parameter_29
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_30
            paddle.uniform([512, 128], dtype='float16', min=0, max=0.5),
            # parameter_31
            paddle.uniform([128], dtype='float16', min=0, max=0.5),
            # parameter_33
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_32
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_34
            paddle.uniform([512, 256], dtype='float16', min=0, max=0.5),
            # parameter_36
            paddle.uniform([256], dtype='float32', min=0, max=0.5),
            # parameter_35
            paddle.uniform([256], dtype='float32', min=0, max=0.5),
            # parameter_37
            paddle.uniform([256, 768], dtype='float16', min=0, max=0.5),
            # parameter_38
            paddle.uniform([768], dtype='float16', min=0, max=0.5),
            # parameter_39
            paddle.uniform([1, 8, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_40
            paddle.uniform([256, 256], dtype='float16', min=0, max=0.5),
            # parameter_41
            paddle.uniform([256], dtype='float16', min=0, max=0.5),
            # parameter_43
            paddle.uniform([256], dtype='float32', min=0, max=0.5),
            # parameter_42
            paddle.uniform([256], dtype='float32', min=0, max=0.5),
            # parameter_44
            paddle.uniform([256, 1024], dtype='float16', min=0, max=0.5),
            # parameter_45
            paddle.uniform([1024], dtype='float16', min=0, max=0.5),
            # parameter_46
            paddle.uniform([1024, 256], dtype='float16', min=0, max=0.5),
            # parameter_47
            paddle.uniform([256], dtype='float16', min=0, max=0.5),
            # parameter_49
            paddle.uniform([256], dtype='float32', min=0, max=0.5),
            # parameter_48
            paddle.uniform([256], dtype='float32', min=0, max=0.5),
            # parameter_50
            paddle.uniform([256, 768], dtype='float16', min=0, max=0.5),
            # parameter_51
            paddle.uniform([768], dtype='float16', min=0, max=0.5),
            # parameter_52
            paddle.uniform([1, 8, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_55
            paddle.uniform([256, 256], dtype='float16', min=0, max=0.5),
            # parameter_56
            paddle.uniform([256], dtype='float16', min=0, max=0.5),
            # parameter_58
            paddle.uniform([256], dtype='float32', min=0, max=0.5),
            # parameter_57
            paddle.uniform([256], dtype='float32', min=0, max=0.5),
            # parameter_59
            paddle.uniform([256, 1024], dtype='float16', min=0, max=0.5),
            # parameter_60
            paddle.uniform([1024], dtype='float16', min=0, max=0.5),
            # parameter_61
            paddle.uniform([1024, 256], dtype='float16', min=0, max=0.5),
            # parameter_62
            paddle.uniform([256], dtype='float16', min=0, max=0.5),
            # parameter_64
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_63
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_65
            paddle.uniform([1024, 512], dtype='float16', min=0, max=0.5),
            # parameter_67
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_66
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_68
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_69
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_70
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_71
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_72
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_74
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_73
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_75
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_76
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_77
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_78
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_80
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_79
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_81
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_82
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_83
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_86
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_87
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_89
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_88
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_90
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_91
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_92
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_93
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_95
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_94
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_96
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_97
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_98
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_99
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_100
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_102
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_101
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_103
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_104
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_105
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_106
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_108
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_107
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_109
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_110
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_111
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_113
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_114
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_116
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_115
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_117
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_118
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_119
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_120
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_122
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_121
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_123
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_124
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_125
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_126
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_127
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_129
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_128
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_130
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_131
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_132
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_133
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_135
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_134
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_136
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_137
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_138
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_140
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_141
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_143
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_142
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_144
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_145
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_146
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_147
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_149
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_148
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_150
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_151
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_152
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_153
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_154
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_156
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_155
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_157
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_158
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_159
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_160
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_162
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_161
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_163
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_164
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_165
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_167
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_168
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_170
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_169
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_171
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_172
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_173
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_174
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_176
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_175
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_177
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_178
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_179
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_180
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_181
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_183
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_182
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_184
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_185
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_186
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_187
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_189
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_188
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_190
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_191
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_192
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_194
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_195
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_197
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_196
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_198
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_199
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_200
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_201
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_203
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_202
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_204
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_205
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_206
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_207
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_208
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_210
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_209
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_211
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_212
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_213
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_214
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_216
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_215
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_217
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_218
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_219
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_221
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_222
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_224
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_223
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_225
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_226
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_227
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_228
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_230
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_229
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_231
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_232
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_233
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_234
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_235
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_237
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_236
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_238
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_239
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_240
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_241
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_243
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_242
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_244
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_245
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_246
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_248
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_249
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_251
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_250
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_252
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_253
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_254
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_255
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_257
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_256
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_258
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_259
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_260
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_261
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_262
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_264
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_263
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_265
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_266
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_267
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_268
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_270
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_269
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_271
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_272
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_273
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_275
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_276
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_278
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_277
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_279
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_280
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_281
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_282
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_284
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_283
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_285
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_286
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_287
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_288
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_289
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_291
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_290
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_292
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_293
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_294
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_295
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_297
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_296
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_298
            paddle.uniform([512, 1536], dtype='float16', min=0, max=0.5),
            # parameter_299
            paddle.uniform([1536], dtype='float16', min=0, max=0.5),
            # parameter_300
            paddle.uniform([1, 16, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_302
            paddle.uniform([512, 512], dtype='float16', min=0, max=0.5),
            # parameter_303
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_305
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_304
            paddle.uniform([512], dtype='float32', min=0, max=0.5),
            # parameter_306
            paddle.uniform([512, 2048], dtype='float16', min=0, max=0.5),
            # parameter_307
            paddle.uniform([2048], dtype='float16', min=0, max=0.5),
            # parameter_308
            paddle.uniform([2048, 512], dtype='float16', min=0, max=0.5),
            # parameter_309
            paddle.uniform([512], dtype='float16', min=0, max=0.5),
            # parameter_311
            paddle.uniform([2048], dtype='float32', min=0, max=0.5),
            # parameter_310
            paddle.uniform([2048], dtype='float32', min=0, max=0.5),
            # parameter_312
            paddle.uniform([2048, 1024], dtype='float16', min=0, max=0.5),
            # parameter_314
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_313
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_315
            paddle.uniform([1024, 3072], dtype='float16', min=0, max=0.5),
            # parameter_316
            paddle.uniform([3072], dtype='float16', min=0, max=0.5),
            # parameter_317
            paddle.uniform([1, 32, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_318
            paddle.uniform([1024, 1024], dtype='float16', min=0, max=0.5),
            # parameter_319
            paddle.uniform([1024], dtype='float16', min=0, max=0.5),
            # parameter_321
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_320
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_322
            paddle.uniform([1024, 4096], dtype='float16', min=0, max=0.5),
            # parameter_323
            paddle.uniform([4096], dtype='float16', min=0, max=0.5),
            # parameter_324
            paddle.uniform([4096, 1024], dtype='float16', min=0, max=0.5),
            # parameter_325
            paddle.uniform([1024], dtype='float16', min=0, max=0.5),
            # parameter_327
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_326
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_328
            paddle.uniform([1024, 3072], dtype='float16', min=0, max=0.5),
            # parameter_329
            paddle.uniform([3072], dtype='float16', min=0, max=0.5),
            # parameter_330
            paddle.uniform([1, 32, 144, 144], dtype='float16', min=0, max=0.5),
            # parameter_331
            paddle.uniform([1024, 1024], dtype='float16', min=0, max=0.5),
            # parameter_332
            paddle.uniform([1024], dtype='float16', min=0, max=0.5),
            # parameter_334
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_333
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_335
            paddle.uniform([1024, 4096], dtype='float16', min=0, max=0.5),
            # parameter_336
            paddle.uniform([4096], dtype='float16', min=0, max=0.5),
            # parameter_337
            paddle.uniform([4096, 1024], dtype='float16', min=0, max=0.5),
            # parameter_338
            paddle.uniform([1024], dtype='float16', min=0, max=0.5),
            # parameter_340
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_339
            paddle.uniform([1024], dtype='float32', min=0, max=0.5),
            # parameter_341
            paddle.uniform([1024, 1000], dtype='float16', min=0, max=0.5),
            # parameter_342
            paddle.uniform([1000], dtype='float16', min=0, max=0.5),
            # feed_0
            paddle.uniform([1, 3, 384, 384], dtype='float32', min=0, max=0.5),
        ]
        for input in self.inputs:
            input.stop_gradient = True

    def apply_to_static(self, net, use_cinn):
        build_strategy = paddle.static.BuildStrategy()
        input_spec = [
            # constant_46
            paddle.static.InputSpec(shape=[2], dtype='int64'),
            # constant_45
            paddle.static.InputSpec(shape=[6], dtype='int64'),
            # constant_44
            paddle.static.InputSpec(shape=[3], dtype='int64'),
            # constant_43
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # constant_42
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_41
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # parameter_301
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # parameter_274
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # parameter_247
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # parameter_220
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # parameter_193
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # parameter_166
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # parameter_139
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # parameter_112
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # constant_40
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # parameter_85
            paddle.static.InputSpec(shape=[1, 4, 1, 144, 144], dtype='float16'),
            # parameter_84
            paddle.static.InputSpec(shape=[], dtype='int32'),
            # constant_39
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # constant_38
            paddle.static.InputSpec(shape=[6], dtype='int64'),
            # constant_37
            paddle.static.InputSpec(shape=[3], dtype='int64'),
            # constant_36
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # constant_35
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_34
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_33
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_32
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # parameter_54
            paddle.static.InputSpec(shape=[1, 16, 1, 144, 144], dtype='float16'),
            # constant_31
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # parameter_53
            paddle.static.InputSpec(shape=[], dtype='int32'),
            # constant_30
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # constant_29
            paddle.static.InputSpec(shape=[6], dtype='int64'),
            # constant_28
            paddle.static.InputSpec(shape=[3], dtype='int64'),
            # constant_27
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # constant_26
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_25
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_24
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_23
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_22
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_21
            paddle.static.InputSpec(shape=[2], dtype='int64'),
            # constant_20
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # parameter_23
            paddle.static.InputSpec(shape=[1, 64, 1, 144, 144], dtype='float16'),
            # constant_19
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # parameter_22
            paddle.static.InputSpec(shape=[], dtype='int32'),
            # constant_18
            paddle.static.InputSpec(shape=[2], dtype='int64'),
            # constant_17
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_16
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # constant_15
            paddle.static.InputSpec(shape=[6], dtype='int64'),
            # constant_14
            paddle.static.InputSpec(shape=[1], dtype='float32'),
            # constant_13
            paddle.static.InputSpec(shape=[1], dtype='int64'),
            # constant_12
            paddle.static.InputSpec(shape=[1], dtype='int64'),
            # constant_11
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_10
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_9
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_8
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_7
            paddle.static.InputSpec(shape=[3], dtype='int64'),
            # constant_6
            paddle.static.InputSpec(shape=[4], dtype='int64'),
            # constant_5
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_4
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_3
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_2
            paddle.static.InputSpec(shape=[1], dtype='int32'),
            # constant_1
            paddle.static.InputSpec(shape=[1], dtype='int64'),
            # constant_0
            paddle.static.InputSpec(shape=[1], dtype='int64'),
            # parameter_1
            paddle.static.InputSpec(shape=[1, 128, 1, 1], dtype='float16'),
            # parameter_0
            paddle.static.InputSpec(shape=[128, 3, 4, 4], dtype='float16'),
            # parameter_3
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_2
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_5
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_4
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_6
            paddle.static.InputSpec(shape=[128, 384], dtype='float16'),
            # parameter_7
            paddle.static.InputSpec(shape=[384], dtype='float16'),
            # parameter_8
            paddle.static.InputSpec(shape=[1, 4, 144, 144], dtype='float16'),
            # parameter_9
            paddle.static.InputSpec(shape=[128, 128], dtype='float16'),
            # parameter_10
            paddle.static.InputSpec(shape=[128], dtype='float16'),
            # parameter_12
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_11
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_13
            paddle.static.InputSpec(shape=[128, 512], dtype='float16'),
            # parameter_14
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_15
            paddle.static.InputSpec(shape=[512, 128], dtype='float16'),
            # parameter_16
            paddle.static.InputSpec(shape=[128], dtype='float16'),
            # parameter_18
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_17
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_19
            paddle.static.InputSpec(shape=[128, 384], dtype='float16'),
            # parameter_20
            paddle.static.InputSpec(shape=[384], dtype='float16'),
            # parameter_21
            paddle.static.InputSpec(shape=[1, 4, 144, 144], dtype='float16'),
            # parameter_24
            paddle.static.InputSpec(shape=[128, 128], dtype='float16'),
            # parameter_25
            paddle.static.InputSpec(shape=[128], dtype='float16'),
            # parameter_27
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_26
            paddle.static.InputSpec(shape=[128], dtype='float32'),
            # parameter_28
            paddle.static.InputSpec(shape=[128, 512], dtype='float16'),
            # parameter_29
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_30
            paddle.static.InputSpec(shape=[512, 128], dtype='float16'),
            # parameter_31
            paddle.static.InputSpec(shape=[128], dtype='float16'),
            # parameter_33
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_32
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_34
            paddle.static.InputSpec(shape=[512, 256], dtype='float16'),
            # parameter_36
            paddle.static.InputSpec(shape=[256], dtype='float32'),
            # parameter_35
            paddle.static.InputSpec(shape=[256], dtype='float32'),
            # parameter_37
            paddle.static.InputSpec(shape=[256, 768], dtype='float16'),
            # parameter_38
            paddle.static.InputSpec(shape=[768], dtype='float16'),
            # parameter_39
            paddle.static.InputSpec(shape=[1, 8, 144, 144], dtype='float16'),
            # parameter_40
            paddle.static.InputSpec(shape=[256, 256], dtype='float16'),
            # parameter_41
            paddle.static.InputSpec(shape=[256], dtype='float16'),
            # parameter_43
            paddle.static.InputSpec(shape=[256], dtype='float32'),
            # parameter_42
            paddle.static.InputSpec(shape=[256], dtype='float32'),
            # parameter_44
            paddle.static.InputSpec(shape=[256, 1024], dtype='float16'),
            # parameter_45
            paddle.static.InputSpec(shape=[1024], dtype='float16'),
            # parameter_46
            paddle.static.InputSpec(shape=[1024, 256], dtype='float16'),
            # parameter_47
            paddle.static.InputSpec(shape=[256], dtype='float16'),
            # parameter_49
            paddle.static.InputSpec(shape=[256], dtype='float32'),
            # parameter_48
            paddle.static.InputSpec(shape=[256], dtype='float32'),
            # parameter_50
            paddle.static.InputSpec(shape=[256, 768], dtype='float16'),
            # parameter_51
            paddle.static.InputSpec(shape=[768], dtype='float16'),
            # parameter_52
            paddle.static.InputSpec(shape=[1, 8, 144, 144], dtype='float16'),
            # parameter_55
            paddle.static.InputSpec(shape=[256, 256], dtype='float16'),
            # parameter_56
            paddle.static.InputSpec(shape=[256], dtype='float16'),
            # parameter_58
            paddle.static.InputSpec(shape=[256], dtype='float32'),
            # parameter_57
            paddle.static.InputSpec(shape=[256], dtype='float32'),
            # parameter_59
            paddle.static.InputSpec(shape=[256, 1024], dtype='float16'),
            # parameter_60
            paddle.static.InputSpec(shape=[1024], dtype='float16'),
            # parameter_61
            paddle.static.InputSpec(shape=[1024, 256], dtype='float16'),
            # parameter_62
            paddle.static.InputSpec(shape=[256], dtype='float16'),
            # parameter_64
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_63
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_65
            paddle.static.InputSpec(shape=[1024, 512], dtype='float16'),
            # parameter_67
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_66
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_68
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_69
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_70
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_71
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_72
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_74
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_73
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_75
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_76
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_77
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_78
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_80
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_79
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_81
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_82
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_83
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_86
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_87
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_89
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_88
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_90
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_91
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_92
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_93
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_95
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_94
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_96
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_97
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_98
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_99
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_100
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_102
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_101
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_103
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_104
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_105
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_106
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_108
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_107
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_109
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_110
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_111
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_113
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_114
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_116
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_115
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_117
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_118
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_119
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_120
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_122
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_121
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_123
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_124
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_125
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_126
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_127
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_129
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_128
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_130
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_131
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_132
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_133
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_135
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_134
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_136
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_137
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_138
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_140
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_141
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_143
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_142
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_144
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_145
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_146
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_147
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_149
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_148
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_150
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_151
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_152
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_153
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_154
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_156
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_155
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_157
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_158
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_159
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_160
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_162
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_161
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_163
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_164
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_165
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_167
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_168
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_170
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_169
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_171
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_172
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_173
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_174
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_176
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_175
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_177
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_178
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_179
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_180
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_181
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_183
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_182
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_184
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_185
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_186
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_187
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_189
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_188
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_190
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_191
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_192
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_194
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_195
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_197
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_196
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_198
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_199
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_200
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_201
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_203
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_202
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_204
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_205
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_206
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_207
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_208
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_210
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_209
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_211
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_212
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_213
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_214
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_216
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_215
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_217
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_218
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_219
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_221
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_222
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_224
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_223
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_225
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_226
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_227
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_228
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_230
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_229
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_231
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_232
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_233
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_234
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_235
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_237
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_236
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_238
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_239
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_240
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_241
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_243
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_242
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_244
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_245
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_246
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_248
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_249
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_251
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_250
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_252
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_253
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_254
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_255
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_257
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_256
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_258
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_259
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_260
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_261
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_262
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_264
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_263
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_265
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_266
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_267
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_268
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_270
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_269
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_271
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_272
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_273
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_275
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_276
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_278
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_277
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_279
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_280
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_281
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_282
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_284
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_283
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_285
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_286
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_287
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_288
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_289
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_291
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_290
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_292
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_293
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_294
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_295
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_297
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_296
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_298
            paddle.static.InputSpec(shape=[512, 1536], dtype='float16'),
            # parameter_299
            paddle.static.InputSpec(shape=[1536], dtype='float16'),
            # parameter_300
            paddle.static.InputSpec(shape=[1, 16, 144, 144], dtype='float16'),
            # parameter_302
            paddle.static.InputSpec(shape=[512, 512], dtype='float16'),
            # parameter_303
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_305
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_304
            paddle.static.InputSpec(shape=[512], dtype='float32'),
            # parameter_306
            paddle.static.InputSpec(shape=[512, 2048], dtype='float16'),
            # parameter_307
            paddle.static.InputSpec(shape=[2048], dtype='float16'),
            # parameter_308
            paddle.static.InputSpec(shape=[2048, 512], dtype='float16'),
            # parameter_309
            paddle.static.InputSpec(shape=[512], dtype='float16'),
            # parameter_311
            paddle.static.InputSpec(shape=[2048], dtype='float32'),
            # parameter_310
            paddle.static.InputSpec(shape=[2048], dtype='float32'),
            # parameter_312
            paddle.static.InputSpec(shape=[2048, 1024], dtype='float16'),
            # parameter_314
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_313
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_315
            paddle.static.InputSpec(shape=[1024, 3072], dtype='float16'),
            # parameter_316
            paddle.static.InputSpec(shape=[3072], dtype='float16'),
            # parameter_317
            paddle.static.InputSpec(shape=[1, 32, 144, 144], dtype='float16'),
            # parameter_318
            paddle.static.InputSpec(shape=[1024, 1024], dtype='float16'),
            # parameter_319
            paddle.static.InputSpec(shape=[1024], dtype='float16'),
            # parameter_321
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_320
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_322
            paddle.static.InputSpec(shape=[1024, 4096], dtype='float16'),
            # parameter_323
            paddle.static.InputSpec(shape=[4096], dtype='float16'),
            # parameter_324
            paddle.static.InputSpec(shape=[4096, 1024], dtype='float16'),
            # parameter_325
            paddle.static.InputSpec(shape=[1024], dtype='float16'),
            # parameter_327
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_326
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_328
            paddle.static.InputSpec(shape=[1024, 3072], dtype='float16'),
            # parameter_329
            paddle.static.InputSpec(shape=[3072], dtype='float16'),
            # parameter_330
            paddle.static.InputSpec(shape=[1, 32, 144, 144], dtype='float16'),
            # parameter_331
            paddle.static.InputSpec(shape=[1024, 1024], dtype='float16'),
            # parameter_332
            paddle.static.InputSpec(shape=[1024], dtype='float16'),
            # parameter_334
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_333
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_335
            paddle.static.InputSpec(shape=[1024, 4096], dtype='float16'),
            # parameter_336
            paddle.static.InputSpec(shape=[4096], dtype='float16'),
            # parameter_337
            paddle.static.InputSpec(shape=[4096, 1024], dtype='float16'),
            # parameter_338
            paddle.static.InputSpec(shape=[1024], dtype='float16'),
            # parameter_340
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_339
            paddle.static.InputSpec(shape=[1024], dtype='float32'),
            # parameter_341
            paddle.static.InputSpec(shape=[1024, 1000], dtype='float16'),
            # parameter_342
            paddle.static.InputSpec(shape=[1000], dtype='float16'),
            # feed_0
            paddle.static.InputSpec(shape=[None, 3, 384, 384], dtype='float32'),
        ]
        build_strategy.build_cinn_pass = use_cinn
        return paddle.jit.to_static(
            net,
            input_spec=input_spec,
            build_strategy=build_strategy,
            full_graph=True,
        )

    def entry(self, use_cinn):
        net = ModuleOp()
        if GetEnvVarEnableJit():
            net = self.apply_to_static(net, use_cinn)
        paddle.seed(2024)
        out = net(*self.inputs)
        return out

    def test_entry(self):
        if AthenaTryRunEnabled():
            if try_run_exit_code == 0:
                # All unittest cases passed.
                return
            if try_run_exit_code < 0:
                # program panicked.
                raise RuntimeError(f"panicked. panic stderr have been reported by the unittest `TestTryRun.test_panic`.")
        self._test_entry()

if __name__ == '__main__':
    unittest.main()