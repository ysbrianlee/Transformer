# Copyright 2022 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for runtime_client."""

from google.protobuf import text_format
from tensorflow.core.framework import function_pb2
from tensorflow.core.function.runtime_client import runtime_client
from tensorflow.core.function.testing import test_pass
from tensorflow.python import tf2
from tensorflow.python.eager import context
from tensorflow.python.eager import def_function
from tensorflow.python.eager import execute
from tensorflow.python.eager import remote
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import ops
from tensorflow.python.framework import test_util
from tensorflow.python.ops import math_ops
from tensorflow.python.platform import test


class RuntimeClientTest(test.TestCase):

  def test_create_nullary(self):
    fndef = text_format.Parse(
        """
            signature {
               name: 'NullaryFunction'
               output_arg { name: 'o' type: DT_INT32 }
             }
             node_def {
               name: 'retval'
               op: 'Const'
               attr {
                 key: 'dtype'
                 value { type: DT_INT32 }
               }
               attr {
                 key: 'value'
                 value {
                   tensor {
                     dtype: DT_INT32
                     tensor_shape {}
                     int_val: 1
                   }
                 }
               }
             }
             ret { key: 'o' value: 'retval:output' }
         """,
        function_pb2.FunctionDef(),
    )

    ctx = runtime_client.GlobalEagerContext()
    rt = runtime_client.Runtime(ctx)
    rt.CreateFunction(fndef)

  def test_create_function_called_by_py_runtime(self):
    if not tf2.enabled():
      self.skipTest("TF2 test")

    fndef = text_format.Parse(
        """
            signature {
               name: 'NullaryFunction'
               output_arg { name: 'o' type: DT_INT32 }
             }
             node_def {
               name: 'retval'
               op: 'Const'
               attr {
                 key: 'dtype'
                 value { type: DT_INT32 }
               }
               attr {
                 key: 'value'
                 value {
                   tensor {
                     dtype: DT_INT32
                     tensor_shape {}
                     int_val: 1
                   }
                 }
               }
             }
             ret { key: 'o' value: 'retval:output' }
         """,
        function_pb2.FunctionDef(),
    )

    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)
    rt.CreateFunction(fndef)

    ret, = execute.execute("NullaryFunction", 1, [], (), context.context())
    self.assertAllEqual(ret, 1)

  def test_get_function_proto_from_py_runtime_function(self):
    if not tf2.enabled():
      self.skipTest("TF2 test")

    @def_function.function
    def f():
      return 1

    cf = f.get_concrete_function()

    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)
    fndef = rt.GetFunctionProto(cf.function_def.signature.name)

    self.assertEqual(fndef.signature.name, cf.function_def.signature.name)

  def test_concrete_function_editing_proto_executed_directly(self):
    if not tf2.enabled():
      self.skipTest("TF2 test")

    @def_function.function
    def f():
      return 1

    cf = f.get_concrete_function()

    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)
    fndef = rt.GetFunctionProto(cf.function_def.signature.name)

    fndef.node_def[0].attr["value"].tensor.int_val[0] = 2

    rt.CreateFunction(fndef)

    ret, = execute.execute(fndef.signature.name, 1, [], (), context.context())
    self.assertAllEqual(ret, 2)

  def test_concrete_function_editing_proto(self):
    if not tf2.enabled():
      self.skipTest("TF2 test")

    @def_function.function
    def f():
      return 1

    cf = f.get_concrete_function()

    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)
    fndef = rt.GetFunctionProto(cf.function_def.signature.name)

    fndef.node_def[0].attr["value"].tensor.int_val[0] = 2

    rt.CreateFunction(fndef)

    self.assertAllEqual(self.evaluate(f()), 2)

  def test_concrete_function_editing_proto_after_instantiation(self):
    if not tf2.enabled():
      self.skipTest("TF2 test")

    @def_function.function
    def f():
      return 1

    cf = f.get_concrete_function()

    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)
    fndef = rt.GetFunctionProto(cf.function_def.signature.name)

    fndef.node_def[0].attr["value"].tensor.int_val[0] = 2

    rt.CreateFunction(fndef)

    self.assertAllEqual(self.evaluate(f()), 2)

  def test_concrete_function_editing_via_mlir_pass_tfg_dialect(self):
    if not tf2.enabled():
      self.skipTest("TF2 test")

    @def_function.function
    def f(x, y):
      return math_ops.add(x, y, name="x_plus_y")

    one = constant_op.constant(1)
    cf = f.get_concrete_function(one, one)

    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)
    rt.TransformFunction(cf.function_def.signature.name, "test-pass")

    # 1 + 1 = 2. But the pass changes it to 1 * 1.
    self.assertAllEqual(self.evaluate(f(one, one)), 1)

  def test_concrete_function_editing_via_mlir_pass_tf_dialect(self):
    if not tf2.enabled():
      self.skipTest("TF2 test")

    @def_function.function
    def f(x, y):
      return math_ops.multiply(x, y, name="x_times_y")

    one = constant_op.constant(1)
    cf = f.get_concrete_function(one, one)
    fname = cf.function_def.signature.name
    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)

    # 1 * 1 = 1 -> 1 + 1 = 2
    rt.TransformFunction(
        fname, "test-pass-tf-dialect", runtime_client.Runtime.Dialect.TF
    )

    self.assertAllEqual(f(one, one), 2)

  def test_concrete_function_editing_via_mlir_pass_mixed_dialects(self):
    if not tf2.enabled():
      self.skipTest("TF2 test")

    @def_function.function
    def f(x, y):
      return math_ops.add(x, y, name="x_plus_y")

    one = constant_op.constant(1)
    cf = f.get_concrete_function(one, one)
    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)
    fname = cf.function_def.signature.name

    # 1 + 1 = 2 -> 1 * 1 = 1
    rt.TransformFunction(fname, "test-pass")

    self.assertAllEqual(f(one, one), 1)

    # 1 * 1 = 1 -> 1 + 1 = 2
    rt.TransformFunction(
        fname, "test-pass-tf-dialect", runtime_client.Runtime.Dialect.TF
    )

    self.assertAllEqual(f(one, one), 2)


class RuntimeClientMultiWorkersTest(test.TestCase):

  @test_util.run_v2_only
  def setUp(self):
    super().setUp()

    workers, _ = test_util.create_local_cluster(2, 0)

    remote.connect_to_remote_host(
        [workers[0].target, workers[1].target])

    self.device0 = "/job:worker/replica:0/task:0/device:CPU:0"
    self.device1 = "/job:worker/replica:0/task:1/device:CPU:0"

  @test_util.run_v2_only
  def tearDown(self):
    super().tearDown()
    # Clear the current device scope to avoid polluting other test cases.
    ops.device(None).__enter__()
    # Reset the context to avoid polluting other test cases.
    context._reset_context()

  @test_util.run_v2_only
  def test_transform_function_in_remote_contexts(self):
    """Tests if function_defs in remote contexts could be transformed."""

    @def_function.function
    def add(x, y):
      return math_ops.add(x, y, name="x_plus_y")

    inputs = [1.0, 2.0]

    with ops.device(self.device0):
      result = add(*inputs)

    self.assertAllEqual(result, 3.0)
    self.assertEqual(result.device, self.device0)

    with ops.device(self.device1):
      result = add(*inputs)

    self.assertAllEqual(result, 3.0)
    self.assertEqual(result.device, self.device1)

    cf = add.get_concrete_function(*inputs)
    function_name = cf.function_def.signature.name

    ctx = runtime_client.GlobalPythonEagerContext()
    rt = runtime_client.Runtime(ctx)
    # "test-pass" converts add to multiply.
    rt.TransformFunction(function_name, "test-pass")
    fndef = rt.GetFunctionProto(function_name)
    rt.CreateFunction(fndef)

    with ops.device(self.device0):
      result = add(*inputs)

    self.assertAllEqual(result, 2.0)
    self.assertEqual(result.device, self.device0)

    with ops.device(self.device1):
      result = add(*inputs)

    self.assertAllEqual(result, 2.0)
    self.assertEqual(result.device, self.device1)


if __name__ == "__main__":
  context.set_soft_device_placement(False)
  test_pass.RegisterTestPass()
  test.main()
