"""
Dreamina AI文/图生图合并节点
ComfyUI插件的文生图和图生图功能合并为一个节点
"""

import os
import json
import logging
import torch
import numpy as np
import time
import requests
import io
from PIL import Image
from typing import Dict, Any, Tuple, Optional, List

# 导入核心模块
try:
    # 在ComfyUI环境中使用相对导入
    from .core.token_manager import TokenManager
    from .core.api_client import ApiClient
except ImportError:
    # 在测试环境中使用绝对导入
    from core.token_manager import TokenManager
    from core.api_client import ApiClient

logger = logging.getLogger(__name__)

def _load_config_for_class() -> Dict[str, Any]:
    """
    辅助函数：用于在节点类实例化前加载配置，
    以便为UI输入选项提供动态数据（如模型列表、账号列表）。
    """
    try:
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(plugin_dir, "config.json")
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[DreaminaNode] 无法为UI加载配置文件: {e}。将使用默认值。")
        return {"params": {"models": {}, "ratios": {}, "default_model": "", "default_ratio": ""}, "accounts": []}

class DreaminaImageNode:
    """
    即梦AI文/图生图合并节点
    判断规则对齐 Jimeng：当 ref_image_1..6 中至少存在一张“有效参考图”时走图生图，否则走文生图。
    有效参考图需满足：非 None、是 3 或 4 维张量（支持 batch 取第一张）、数值会被裁剪到 [0,1]。
    """
    def __init__(self):
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.config = self._load_config()
        self.token_manager = None
        self.api_client = None
        self._initialize_components()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        加载插件的 config.json 配置文件。
        """
        try:
            config_path = os.path.join(self.plugin_dir, "config.json")
            if not os.path.exists(config_path):
                template_path = os.path.join(self.plugin_dir, "config.json.template")
                if os.path.exists(template_path):
                    import shutil
                    shutil.copy(template_path, config_path)
                    logger.info("[DreaminaNode] 从模板创建了 config.json")
                else:
                    logger.error("[DreaminaNode] 配置文件和模板文件都不存在！")
                    return {}
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.debug("[DreaminaNode] 配置文件加载成功")
            return config
        except Exception as e:
            logger.error(f"[DreaminaNode] 配置文件加载失败: {e}")
            return {}

    def _is_configured(self) -> bool:
        """
        检查配置是否包含至少一个有效的sessionid。
        """
        accounts = self.config.get("accounts", [])
        if not isinstance(accounts, list) or not accounts:
            return False
        return any(acc.get("sessionid") for acc in accounts)

    def _initialize_components(self):
        """
        基于加载的配置初始化TokenManager和ApiClient。
        """
        if not self.config:
            logger.error("[DreaminaNode] 因配置为空，核心组件初始化失败。")
            return
        try:
            self.token_manager = TokenManager(self.config)
            self.api_client = ApiClient(self.token_manager, self.config)
            logger.debug("[DreaminaNode] 核心组件初始化成功。")
        except Exception as e:
            logger.error(f"[DreaminaNode] 核心组件初始化失败: {e}", exc_info=True)
    
    @classmethod
    def INPUT_TYPES(cls):
        config = _load_config_for_class()
        params = config.get("params", {})
        models = params.get("models", {})
        # 支持 1k/2k/4k 三组分辨率比例映射，与 Jimeng 节点对齐
        ratios_1k = params.get("1k_ratios", {})
        ratios_2k = params.get("2k_ratios", {})
        ratios_4k = params.get("4k_ratios", {})
        accounts = config.get("accounts", [])
        
        defaults = {
            "model": params.get("default_model", "3.0"),
            "resolution": "2k",
            "ratio": params.get("default_ratio", "1:1")
        }
        model_options = list(models.keys()) or ["-"]
        # 比例下拉使用三组比例键的并集，避免依赖当前 params.ratios
        ratio_keys = set()
        if isinstance(ratios_1k, dict): ratio_keys.update(ratios_1k.keys())
        if isinstance(ratios_2k, dict): ratio_keys.update(ratios_2k.keys())
        if isinstance(ratios_4k, dict): ratio_keys.update(ratios_4k.keys())
        ratio_options = list(ratio_keys) or ["-"]
        ratio_options.sort()
        resolution_options = ["1k", "2k", "4k"]
        
        # 生成账号选择选项
        account_options = []
        if accounts:
            for i, account in enumerate(accounts):
                description = account.get("description", f"账号{i+1}")
                account_options.append(description)
        else:
            account_options = ["无可用账号"]

        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "一只可爱的小猫咪"}),
                "account": (account_options, {"default": account_options[0] if account_options else "无可用账号"}),
                "model": (model_options, {"default": defaults["model"]}),
                "resolution": (resolution_options, {"default": defaults["resolution"]}),
                "ratio": (ratio_options, {"default": defaults["ratio"]}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff}),
            },
            "optional": {
                "num_images": ("INT", {"default": 4, "min": 1, "max": 4}),
                "ref_image_1": ("IMAGE", {"tooltip": "参考图1，留空则不使用"}),
                "ref_image_2": ("IMAGE", {"tooltip": "参考图2，留空则不使用"}),
                "ref_image_3": ("IMAGE", {"tooltip": "参考图3，留空则不使用"}),
                "ref_image_4": ("IMAGE", {"tooltip": "参考图4，留空则不使用"}),
                "ref_image_5": ("IMAGE", {"tooltip": "参考图5，留空则不使用"}),
                "ref_image_6": ("IMAGE", {"tooltip": "参考图6，留空则不使用"})
            }
        }


    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("images", "generation_info", "image_urls", "history_id")
    FUNCTION = "generate_images"
    CATEGORY = "即梦AI"
    
    def _wait_for_generation(self, history_id: str, is_image2image: bool = False) -> Optional[List[str]]:
        """
        轮询等待任务完成，支持文生图和图生图两种API。
        """
        timeout_config = self.config.get("timeout", {})
        max_wait_time = timeout_config.get("max_wait_time", 120)
        check_interval = timeout_config.get("check_interval", 10)
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            time.sleep(check_interval)
            logger.info(f"[DreaminaNode] 轮询任务状态: {history_id}")
            if is_image2image:
                res = self.api_client._get_generated_images_by_history_id(history_id)
                # 若网页端拒绝（例如 fail_code=1180），直接终止轮询
                if isinstance(res, dict) and res.get("blocked"):
                    logger.error(f"[DreaminaNode] 网页端拒绝生成: fail_code={res.get('fail_code')}, msg={res.get('fail_msg')}")
                    return None
                image_urls = res
            else:
                image_urls = self.api_client._get_generated_images(history_id)
            if isinstance(image_urls, list) and image_urls:
                logger.info(f"[DreaminaNode] 任务 {history_id} 生成成功")
                # 为每个URL添加history_id参数，以便下游高清化节点使用
                enhanced_urls = self._add_history_id_to_urls(image_urls, history_id)
                return enhanced_urls
        logger.error(f"[DreaminaNode] 等待任务 {history_id} 超时")
        return None

    def _add_history_id_to_urls(self, urls: List[str], history_id: str) -> List[str]:
        """
        为图片URL添加history_id参数，以便下游高清化节点使用。
        
        Args:
            urls: 原始图片URL列表
            history_id: 历史记录ID
            
        Returns:
            List[str]: 包含history_id参数的URL列表
        """
        enhanced_urls = []
        for url in urls:
            if '?' in url:
                # URL已经有参数，添加history_id
                enhanced_url = f"{url}&history_id={history_id}"
            else:
                # URL没有参数，直接添加history_id
                enhanced_url = f"{url}?history_id={history_id}"
            enhanced_urls.append(enhanced_url)
        return enhanced_urls

    def _download_images(self, urls: List[str]) -> List[torch.Tensor]:
        """
        下载图片并转换为torch张量。
        """
        images = []
        for url in urls:
            try:
                # 移除history_id参数，因为下载图片时不需要这个参数
                clean_url = self._remove_history_id_from_url(url)
                response = requests.get(clean_url, timeout=60)
                response.raise_for_status()
                img_data = response.content
                pil_image = Image.open(io.BytesIO(img_data)).convert("RGB")
                np_image = np.array(pil_image, dtype=np.float32) / 255.0
                tensor_image = torch.from_numpy(np_image).unsqueeze(0)
                images.append(tensor_image)
            except Exception as e:
                logger.error(f"[DreaminaNode] 下载或处理图片失败 {url}: {e}")
                continue
        return images

    def _remove_history_id_from_url(self, url: str) -> str:
        """
        从URL中移除history_id参数，用于图片下载。
        
        Args:
            url: 包含history_id参数的URL
            
        Returns:
            str: 清理后的URL
        """
        if 'history_id=' in url:
            # 移除history_id参数
            if '&history_id=' in url:
                # history_id在中间或末尾
                url = url.replace('&history_id=', '&').replace('&&', '&')
                if url.endswith('&'):
                    url = url[:-1]
            elif '?history_id=' in url:
                # history_id是第一个参数
                if '&' in url:
                    # 还有其他参数
                    url = url.replace('?history_id=', '?').replace('&&', '&')
                else:
                    # 只有history_id参数
                    url = url.split('?history_id=')[0]
        return url



    def _validate_image_tensor(self, t: torch.Tensor) -> bool:
        """
        校验参考图张量是否有效：
        - 非 None
        - torch.Tensor 类型
        - 维度为 3 或 4（4 维时会取第一张）
        """
        try:
            if t is None or not isinstance(t, torch.Tensor):
                return False
            if len(t.shape) not in (3, 4):
                return False
            return True
        except Exception:
            return False

    def _save_input_image(self, image_tensor: torch.Tensor) -> str:
        """
        将输入的图像张量保存为临时文件。
        """
        try:
            temp_dir = os.path.join(self.plugin_dir, "temp")
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, f"temp_input_{int(time.time())}.png")
            if len(image_tensor.shape) == 4:
                image_tensor = image_tensor[0]
            image_tensor = torch.clamp(image_tensor, 0, 1)
            image_np = (image_tensor.cpu().numpy() * 255).astype(np.uint8)
            image_pil = Image.fromarray(image_np)
            image_pil.save(temp_path)
            logger.info(f"[DreaminaNode] 输入图像已保存到: {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"[DreaminaNode] 保存输入图像失败: {e}")
            return None

    def _get_account_index_by_description(self, account_description: str) -> Optional[int]:
        """
        根据账号描述找到对应的账号索引
        
        Args:
            account_description: 账号描述（如"账号1"、"账号2"等）
            
        Returns:
            int: 账号索引，如果未找到则返回None
        """
        try:
            accounts = self.config.get("accounts", [])
            for i, account in enumerate(accounts):
                description = account.get("description", f"账号{i+1}")
                if description == account_description:
                    return i
            
            # 如果没有找到精确匹配，尝试处理"无可用账号"的情况
            if account_description == "无可用账号":
                return None
                
            logger.warning(f"[DreaminaNode] 未找到账号描述: {account_description}")
            return None
        except Exception as e:
            logger.error(f"[DreaminaNode] 查找账号索引时出错: {e}")
            return None

    def generate_images(self, prompt: str, model: str, resolution: str, ratio: str, account: str, seed: int, num_images: int = 4, 
                        ref_image_1: torch.Tensor = None, ref_image_2: torch.Tensor = None, ref_image_3: torch.Tensor = None, 
                        ref_image_4: torch.Tensor = None, ref_image_5: torch.Tensor = None, ref_image_6: torch.Tensor = None) -> Tuple[torch.Tensor, str, str, str]:
        """
        生成图像的主要方法
        """
        try:
            # 检查配置和组件是否正确初始化
            if not self._is_configured():
                error_msg = "插件未正确配置，请检查config.json文件中的账号设置"
                logger.error(f"[DreaminaNode] {error_msg}")
                return self._create_error_result(error_msg)
                
            if not self.token_manager or not self.api_client:
                error_msg = "核心组件未初始化，请重启ComfyUI"
                logger.error(f"[DreaminaNode] {error_msg}")
                return self._create_error_result(error_msg)
            
            # 切换到指定账号
            account_index = self._get_account_index_by_description(account)
            if account_index is None:
                error_msg = f"未找到账号: {account}"
                logger.error(f"[DreaminaNode] {error_msg}")
                return self._create_error_result(error_msg)
                
            self.token_manager.switch_to_account(account_index)
            
            # 收集参考图（最多6张），并做有效性过滤（对齐 Jimeng 逻辑）
            raw_refs = [ref_image_1, ref_image_2, ref_image_3, ref_image_4, ref_image_5, ref_image_6]
            valid_refs = []
            invalid_count = 0
            for i, ri in enumerate(raw_refs, start=1):
                if ri is None:
                    continue
                if self._validate_image_tensor(ri):
                    valid_refs.append(ri)
                else:
                    invalid_count += 1
            if invalid_count > 0:
                logger.warning(f"[DreaminaNode] 有 {invalid_count} 张参考图无效，已忽略")
            ref_images = valid_refs
            is_image2image = len(ref_images) > 0
            logger.info(f"[DreaminaNode] 判定生成类型：{'图生图(I2I)' if is_image2image else '文生图(T2I)'}；有效参考图数量: {len(ref_images)}")
            # 按用户选择的分辨率切换分辨率映射（对文生图/图生图通用）
            try:
                params_cfg = self.config.get("params", {})
                ratios_1k = params_cfg.get("1k_ratios", {})
                ratios_2k = params_cfg.get("2k_ratios", {})
                ratios_4k = params_cfg.get("4k_ratios", {})
                key_map = {"1k": ratios_1k, "2k": ratios_2k, "4k": ratios_4k}
                selected = key_map.get(str(resolution).strip(), ratios_2k)
                if isinstance(selected, dict) and selected:
                    params_cfg["ratios"] = dict(selected)
                    # 同步记录分辨率类型，供 ApiClient.large_image_info.resolution_type 使用
                    if selected is ratios_1k:
                        params_cfg["resolution_type"] = "1k"
                    elif selected is ratios_2k:
                        params_cfg["resolution_type"] = "2k"
                    else:
                        params_cfg["resolution_type"] = "4k"
                    self.config["params"] = params_cfg
                    selected_group = "1k_ratios" if selected is ratios_1k else ("2k_ratios" if selected is ratios_2k else "4k_ratios")
                    logger.info(f"[DreaminaNode] 已切换分辨率组为: {selected_group}")
                else:
                    logger.warning("[DreaminaNode] 未找到匹配的分辨率映射，将使用现有 ratios。")
            except Exception as e:
                logger.warning(f"[DreaminaNode] 切换分辨率映射时出错: {e}")

            # 获取当前积分信息
            logger.info(f"[DreaminaNode] 🔍 正在获取账号积分信息...")
            current_credit = self.token_manager.get_credit()
            
            if current_credit:
                total_credit = current_credit.get("total_credit", 0)
                gift_credit = current_credit.get("gift_credit", 0)
                purchase_credit = current_credit.get("purchase_credit", 0)
                vip_credit = current_credit.get("vip_credit", 0)
                is_free_period = current_credit.get("is_free_period", False)
                
                logger.info(f"[DreaminaNode] 💰 当前积分: {total_credit} (赠送:{gift_credit} 购买:{purchase_credit} VIP:{vip_credit})")
                
                # 检查即将过期的积分
                expiring_credits = current_credit.get("expiring_credits", [])
                if expiring_credits and self.config.get("credit", {}).get("show_expiring_alerts", True):
                    for expiring in expiring_credits:
                        expire_time = expiring.get("expire_time", 0)
                        expire_amount = expiring.get("credit_amount", 0)
                        if expire_time > 0:
                            import datetime
                            expire_date = datetime.datetime.fromtimestamp(expire_time).strftime('%Y-%m-%d %H:%M:%S')
                            days_left = (expire_time - time.time()) / 86400
                            if days_left <= 7:  # 7天内过期的积分提醒
                                logger.warning(f"[DreaminaNode] ⚠️ 积分即将过期: {expire_amount}积分将在{expire_date}过期")
                
                # 估算本次生成的积分消耗 - 按次数计费，不是按图片数量
                # 已基于是否提供参考图进行判断
                
                # 根据生成类型确定积分消耗
                if is_image2image:
                    estimated_cost = 4  # 图生图固定消耗4积分
                    generation_type = "图生图"
                else:
                    estimated_cost = 2  # 文生图固定消耗2积分
                    generation_type = "文生图"
                
                # 也可以从配置文件获取，如果配置了的话
                model_configs = self.config.get("params", {}).get("models", {})
                model_config = model_configs.get(model, {})
                if is_image2image:
                    estimated_cost = model_config.get("cost_per_i2i", estimated_cost)
                else:
                    estimated_cost = model_config.get("cost_per_t2i", estimated_cost)
                
                if self.config.get("ui", {}).get("show_cost_estimation", True):
                    logger.info(f"[DreaminaNode] 💡 本次{generation_type}预估消耗: {estimated_cost}积分")
                
                # 检查积分是否足够（限免期跳过检查）
                if not is_free_period and total_credit < estimated_cost:
                    min_threshold = self.config.get("credit", {}).get("min_credit_threshold", 10)
                    if total_credit < min_threshold:
                        logger.warning(f"[DreaminaNode] ⚠️ 当前积分({total_credit})可能不足，建议检查账号状态")
            else:
                logger.warning("[DreaminaNode] ⚠️ 无法获取积分信息，将继续尝试生成")
            
            # 获取积分历史记录（如果启用）
            credit_config = self.config.get("credit", {})
            if credit_config.get("enable_history", False):
                logger.debug(f"[DreaminaNode] 📊 正在获取积分历史记录...")
                try:
                    history_count = credit_config.get("history_count", 10)
                    credit_history = self.token_manager.get_credit_history(count=history_count)
                    
                    if credit_history:
                        records = credit_history.get("records", [])
                        
                        # 分析最近的积分变化趋势
                        recent_generations = 0
                        recent_recharges = 0
                        
                        for record in records[:5]:  # 只分析最近5条记录
                            title = record.get("title", "")
                            history_type = record.get("history_type", 0)
                            amount = record.get("amount", 0)
                            
                            if "Image generation" in title or history_type == 2:
                                recent_generations += 1
                            elif "Daily free" in title or history_type == 1:
                                recent_recharges += amount
                        
                        if recent_generations > 0:
                            logger.debug(f"[DreaminaNode] 📈 最近活动: {recent_generations}次生成，{recent_recharges}积分获得")
                        else:
                            logger.debug(f"[DreaminaNode] 📈 最近活动: 暂无生成记录，{recent_recharges}积分获得")
                        
                except Exception as e:
                    logger.debug(f"[DreaminaNode] ⚠️ 获取积分历史失败: {e}")
                    # 积分历史查询失败不应该影响主要流程，继续执行
            else:
                logger.debug(f"[DreaminaNode] ℹ️ 积分历史查询功能已禁用")
            
            # 继续原有的生成逻辑...
            # 已基于是否提供参考图进行判断
            
            logger.info(f"[DreaminaNode] 🚀 开始{'图生图' if is_image2image else '文生图'}处理...")
            logger.debug(f"[DreaminaNode] 📝 提示词: {prompt[:50]}...")
            logger.debug(f"[DreaminaNode] 🎨 模型: {model}")
            logger.debug(f"[DreaminaNode] 🖼️ 分辨率: {resolution}")
            logger.debug(f"[DreaminaNode] 📐 比例: {ratio}")
            logger.debug(f"[DreaminaNode] 🎲 种子: {seed}")
            logger.debug(f"[DreaminaNode] 🔢 数量: {num_images}")
            
            if is_image2image:
                # 图生图：传递参考图列表，让API客户端内部处理保存与批量上传
                result = self.api_client.generate_i2i(ref_images, prompt, model, ratio, seed, num_images)
            else:
                result = self.api_client.generate_t2i(prompt, model, ratio, seed)
            
            if not result:
                error_msg = "图像生成失败，请检查网络连接和账号状态"
                logger.error(f"[DreaminaNode] {error_msg}")
                return self._create_error_result(error_msg)
            
            # 处理生成结果 - 区分文生图和图生图的返回格式
            if is_image2image:
                # 图生图：result是元组 (image_batch, generation_info, image_urls, history_id)
                if isinstance(result, tuple) and len(result) == 4:
                    image_batch, basic_generation_info, image_urls, history_id = result
                    
                    # 确保history_id不为空，如果为空则生成一个标识
                    if not history_id:
                        history_id = f"i2i_{int(time.time())}"
                        logger.warning(f"[DreaminaNode] ⚠️ 未能获取history_id，使用生成的ID: {history_id}")
                    
                    # 重新生成完整的信息文本
                    num_generated = image_batch.shape[0] if len(image_batch.shape) > 3 else 1
                    enhanced_generation_info = self._generate_info_text(
                        prompt=prompt, 
                        model=model, 
                        ratio=ratio, 
                        num_images=num_generated, 
                        account=account,
                        generation_type=generation_type,
                        estimated_cost=estimated_cost,
                        current_credit=current_credit,
                        history_id=history_id
                    )
                    
                    return (image_batch, enhanced_generation_info, image_urls, history_id)
                else:
                    error_msg = "图生图返回格式错误"
                    logger.error(f"[DreaminaNode] {error_msg}")
                    return self._create_error_result(error_msg)
            else:
                # 文生图：result是字典格式
                if result.get("is_queued"):
                    queue_message = result.get("queue_message", "")
                    history_id = result.get("history_id", "")
                    info_text = f"任务已提交，正在排队中...\n{queue_message}\n历史ID: {history_id}"
                    logger.info(f"[DreaminaNode] 📋 {queue_message}")
                    
                    # 返回排队信息，不等待完成
                    placeholder_image = torch.zeros((1, 512, 512, 3))
                    return (placeholder_image, info_text, "", history_id)
                
                # 获取生成的图片URLs
                urls = result.get("urls", [])
                history_id = result.get("history_record_id", "")
                submit_id = result.get("submit_id", "")  # 获取submit_id用于查询
                
                # 确保history_id不为空
                if not history_id and submit_id:
                    history_id = submit_id
                elif not history_id:
                    history_id = f"t2i_{int(time.time())}"
                    logger.warning(f"[DreaminaNode] ⚠️ 未能获取history_id，使用生成的ID: {history_id}")
            
                if not urls:
                    # 如果没有URLs但有submit_id，尝试等待一段时间后查询
                    if submit_id:
                        logger.info(f"[DreaminaNode] ⏳ 任务已提交，等待生成完成...")
                        timeout_config = self.config.get("timeout", {})
                        max_wait_time = timeout_config.get("generation_timeout", 180)
                        check_interval = timeout_config.get("check_interval", 10)
                        max_attempts = max_wait_time // check_interval
                        
                        for attempt in range(max_attempts):
                            time.sleep(check_interval)
                            
                            # 只在特定间隔显示查询进度，避免日志过多
                            if attempt % 3 == 0 or attempt == max_attempts - 1:
                                logger.info(f"[DreaminaNode] 🔍 检查生成状态... ({attempt + 1}/{max_attempts})")
                            
                            # 文生图使用submit_id查询
                            check_result = self.api_client._get_generated_images(submit_id)
                            
                            if check_result:
                                urls = check_result
                                break
                    elif history_id:
                        # 备用：如果没有submit_id但有history_id，记录警告并尝试使用history_id
                        logger.warning(f"[DreaminaNode] ⚠️ 缺少submit_id，尝试使用history_id查询（可能不准确）")
                        submit_id = history_id  # 作为备用方案
                    
                    if not urls:
                        error_msg = f"生成超时或失败，历史ID: {history_id}"
                        logger.error(f"[DreaminaNode] {error_msg}")
                        return self._create_error_result(error_msg)
                
                # 下载图片
                logger.info(f"[DreaminaNode] 📥 开始下载{len(urls)}张图片...")
                images = self.api_client._download_images(urls)
                
                if not images:
                    error_msg = f"图片下载失败，历史ID: {history_id}"
                    logger.error(f"[DreaminaNode] {error_msg}")
                    return self._create_error_result(error_msg)
                
                # 转换为张量
                if len(images) == 1:
                    result_images = images[0]
                else:
                    result_images = torch.cat(images, dim=0)
                
                # 生成信息文本
                info_text = self._generate_info_text(
                    prompt=prompt, 
                    model=model, 
                    ratio=ratio, 
                    num_images=len(images), 
                    account=account,
                    generation_type=generation_type,
                    estimated_cost=estimated_cost,
                    current_credit=current_credit,
                    history_id=history_id
                )
                
                # 构建URLs字符串（用于历史记录）
                urls_with_history = self._add_history_id_to_urls(urls, history_id)
                urls_string = "\n".join(urls_with_history)
                
                logger.info(f"[DreaminaNode] ✅ 生成完成！共{len(images)}张图片")
                return (result_images, info_text, urls_string, history_id)
            
        except Exception as e:
            error_msg = f"生成过程中发生错误: {str(e)}"
            logger.error(f"[DreaminaNode] {error_msg}")
            import traceback
            logger.error(f"[DreaminaNode] 详细错误信息: {traceback.format_exc()}")
            return self._create_error_result(error_msg)

    def _create_error_result(self, error_msg: str) -> Tuple[torch.Tensor, str, str, str]:
        logger.error(f"[DreaminaNode] {error_msg}")
        error_image = torch.ones(1, 256, 256, 3) * torch.tensor([1.0, 0.0, 0.0])
        return (error_image, f"错误: {error_msg}", "", "")

    def _generate_info_text(self, prompt: str, model: str, ratio: str, num_images: int, account: str = None, 
                           generation_type: str = "生图", estimated_cost: int = 0, 
                           current_credit: dict = None, history_id: str = "") -> str:
        """生成详细的任务信息文本"""
        models_config = self.config.get("params", {}).get("models", {})
        model_display_name = models_config.get(model, {}).get("name", model)
        
        # 基本信息
        info_lines = [
            f"✨ 任务类型: {generation_type}",
            f"📝 提示词: {prompt}",
            f"🎨 模型: {model_display_name}",
            f"📐 比例: {ratio}",
            f"🔢 数量: {num_images}张"
        ]
        
        # 账号信息
        if account:
            info_lines.append(f"👤 当前任务使用账号: {account}")
        
        # 积分信息
        if estimated_cost > 0:
            info_lines.append(f"💎 当前任务消耗积分: {estimated_cost}积分")
            
        if current_credit and not current_credit.get("is_free_period", False):
            total_credit = current_credit.get("total_credit", 0)
            remaining_credit = total_credit - estimated_cost
            info_lines.append(f"💰 当前账号剩余积分: {remaining_credit}积分")
            
        return "\n".join(info_lines)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

# ComfyUI节点注册
NODE_CLASS_MAPPINGS = {
    "Dreamina_Image": DreaminaImageNode
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "Dreamina_Image": "Dreamina AI图片生成"
}
