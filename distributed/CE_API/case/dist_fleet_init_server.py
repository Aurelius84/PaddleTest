#!/bin/env python
# -*- coding: utf-8 -*-
# encoding=utf-8 vi:ts=4:sw=4:expandtab:ft=python
# ======================================================================
#
# Copyright (c) 2017 Baidu.com, Inc. All Rights Reserved
#
# ======================================================================
"""
/***************************************************************************
  *
  * Copyright (c) 2019 Baidu.com, Inc. All Rights Reserved
  * @file dist_fleet_worker_index.py
  * @author liujie44@baidu.com
  * @date 2021-11-20 13:07
  * @brief
  *
  **************************************************************************/
"""
import sys
import paddle.distributed.fleet as fleet
from utils import run_priority


fleet.init()


@run_priority(level="P0")
def test_init_server():
    """test_init_server"""
    assert fleet.init_server() is None
    print("{} ... ok".format(sys._getframe().f_code.co_name))


if __name__ == "__main__":
    test_init_server()