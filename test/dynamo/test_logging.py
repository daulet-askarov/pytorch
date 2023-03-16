# Owner(s): ["module: dynamo"]
import functools
import logging
import unittest.mock

import torch
import torch._dynamo.test_case
import torch._dynamo.testing

from torch.testing._internal.inductor_utils import HAS_CUDA
from torch.testing._internal.logging_utils import (
    LoggingTestCase,
    make_logging_test,
    make_settings_test,
)

requires_cuda = functools.partial(unittest.skipIf, not HAS_CUDA, "requires cuda")


def example_fn(a):
    output = a.mul(torch.ones(1000, 1000))
    output = output.add(torch.ones(1000, 1000))
    output.sum().backward()
    return output


def dynamo_error_fn(a):
    output = a.mul(torch.ones(1000, 1000))
    output = output.add(torch.ones(10, 10))
    return output


def inductor_error_fn(a):
    output = torch.round(a)
    return output


def inductor_schedule_fn(a):
    output = a.add(torch.ones(1000, 1000, device="cuda"))
    return output


ARGS = (torch.ones(1000, 1000, requires_grad=True),)


def multi_record_test(num_records, **kwargs):
    @make_logging_test(**kwargs)
    def fn(self, records):
        fn_opt = torch._dynamo.optimize("inductor")(example_fn)
        fn_opt(*ARGS)
        self.assertEqual(len(records), num_records)

    return fn


def within_range_record_test(num_records_lower, num_records_higher, **kwargs):
    @make_logging_test(**kwargs)
    def fn(self, records):
        fn_opt = torch._dynamo.optimize("inductor")(example_fn)
        fn_opt(*ARGS)
        self.assertGreaterEqual(len(records), num_records_lower)
        self.assertLessEqual(len(records), num_records_higher)

    return fn


def single_record_test(**kwargs):
    return multi_record_test(1, **kwargs)


class LoggingTests(LoggingTestCase):

    test_bytecode = multi_record_test(2, bytecode=True)
    test_output_code = multi_record_test(2, output_code=True)

    @requires_cuda()
    @make_logging_test(schedule=True)
    def test_schedule(self, records):
        fn_opt = torch._dynamo.optimize("inductor")(inductor_schedule_fn)
        fn_opt(torch.ones(1000, 1000, device="cuda"))
        self.assertEqual(len(records), 2)

    test_dynamo_debug = within_range_record_test(30, 50, dynamo=logging.DEBUG)
    test_dynamo_info = within_range_record_test(2, 10, dynamo=logging.INFO)

    @make_logging_test(dynamo=logging.ERROR)
    def test_dynamo_error(self, records):
        try:
            fn_opt = torch._dynamo.optimize("inductor")(dynamo_error_fn)
            fn_opt(*ARGS)
        except Exception:
            pass
        self.assertEqual(len(records), 1)

    test_aot = multi_record_test(3, aot=logging.DEBUG)
    test_inductor_debug = within_range_record_test(5, 15, inductor=logging.DEBUG)
    test_inductor_info = within_range_record_test(2, 4, inductor=logging.INFO)

    @make_logging_test(dynamo=logging.ERROR)
    def test_inductor_error(self, records):
        import torch._inductor.lowering

        def throw(x):
            raise AssertionError()

        # inject an error in the lowerings
        for x in list(torch._inductor.lowering.lowerings.keys()):
            if "round" in x.__name__:
                torch._inductor.lowering.lowerings[x] = throw

        try:
            fn_opt = torch._dynamo.optimize("inductor")(inductor_error_fn)
            fn_opt(*ARGS)
        except Exception:
            pass
        self.assertEqual(len(records), 1)
        self.assertIsInstance(records[0].msg, str)

    @make_settings_test("torch._dynamo.output_graph")
    def test_open_registrarion_with_registered_parent(self, records):
        pass

    @make_settings_test("torch.utils")
    def test_open_registration(self, records):
        pass


# single record tests
exclusions = {"bytecode", "output_code", "schedule"}
for name in torch._logging._internal.log_registry.artifact_names:
    if name not in exclusions:
        setattr(LoggingTests, f"test_{name}", single_record_test(**{name: True}))

if __name__ == "__main__":
    from torch._dynamo.test_case import run_tests

    run_tests()
