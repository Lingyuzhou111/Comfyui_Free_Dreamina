from .dreamina_image_node import DreaminaImageNode

# 节点类映射 - 注册所有节点
NODE_CLASS_MAPPINGS = {
    "Dreamina_Image": DreaminaImageNode,
}

# 节点显示名称映射
NODE_DISPLAY_NAME_MAPPINGS = {
    "Dreamina_Image": "Dreamina AI图片生成",
}

__version__ = "1.0.0"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]