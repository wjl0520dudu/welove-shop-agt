"""pytest 配置：把 ai-service 根目录加入 sys.path。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))