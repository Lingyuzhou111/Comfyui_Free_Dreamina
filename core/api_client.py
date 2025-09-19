import requests
import json
import logging
import os
import time
import uuid
import random
import hashlib
import hmac
import binascii
import datetime
import urllib.parse
import torch
import numpy as np
from PIL import Image
import io
from typing import Dict, Optional, Any, Tuple, List

# 确保从同级目录导入
from .token_manager import TokenManager

logger = logging.getLogger(__name__)

class ApiClient:
    def __init__(self, token_manager, config):
        self.token_manager = token_manager
        self.config = config
        self.temp_files = []
        self.base_url = "https://mweb-api-sg.capcut.com"  # 改回正确的域名
        self.aid = "513641"  # 修改为成功的aid
        self.app_version = "5.8.0"

    def _get_headers(self, uri="/"):
        """获取请求头"""
        token_info = self.token_manager.get_token(uri)
        if not token_info:
            return {}
            
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'app-sdk-version': '48.0.0',
            'appid': '513641',
            'appvr': '5.8.0',
            'content-type': 'application/json',
            'cookie': token_info["cookie"],
            'device-time': token_info["device_time"],
            'lan': 'en',
            'loc': 'US',
            'origin': 'https://dreamina.capcut.com',
            'pf': '7',
            'priority': 'u=1, i',
            'referer': 'https://dreamina.capcut.com/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Microsoft Edge";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'sign': token_info["sign"],
            'sign-ver': '1',
            'tdid': 'web',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
        }
        return headers

    def _send_request(self, method, url, **kwargs):
        """发送HTTP请求"""
        try:
            # 获取URI
            uri = url.split(self.base_url)[-1].split('?')[0]
            
            # 获取headers
            headers = self._get_headers(uri)
            
            # 如果kwargs中有headers，合并它们
            if 'headers' in kwargs:
                headers.update(kwargs.pop('headers'))
            
            kwargs['headers'] = headers
            
            # 简化日志 - 只记录基本请求信息
            logger.debug(f"[Dreamina] 🔄 发送请求: {method} {uri}")
            
            try:
                response = requests.request(method, url, timeout=30, **kwargs)
                logger.debug(f"[Dreamina] ✅ HTTP请求发送成功")
            except requests.exceptions.Timeout as e:
                logger.error(f"[Dreamina] ❌ 请求超时: {e}")
                return None
            except requests.exceptions.ConnectionError as e:
                logger.error(f"[Dreamina] ❌ 连接错误: {e}")
                return None
            except Exception as e:
                logger.error(f"[Dreamina] ❌ 请求发送异常: {e}")
                return None
            
            # 简化响应处理
            logger.debug(f"[Dreamina] 📨 响应状态码: {response.status_code}")
            
            try:
                response_json = response.json()
                # 记录响应JSON的关键信息
                ret_code = response_json.get('ret', 'unknown')
                err_msg = response_json.get('errmsg', 'unknown')
                
                # 如果是错误响应，记录错误信息
                if ret_code != '0':
                    logger.error(f"[Dreamina] ❌ API错误: {ret_code} - {err_msg}")
                
                return response_json
            except json.JSONDecodeError as e:
                logger.error(f"[Dreamina] ❌ 响应不是有效的JSON: {e}")
                return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[Dreamina] ❌ 网络请求异常: {e}")
            return None
        except Exception as e:
            logger.error(f"[Dreamina] ❌ 请求处理异常: {e}")
            return None

    def generate_t2i(self, prompt: str, model: str, ratio: str, seed: int = -1):
        """处理文生图请求 - 更新为最新API格式
        Args:
            prompt: 提示词
            model: 模型名称
            ratio: 图片比例
            seed: 随机种子
        Returns:
            dict: 包含生成的图片URL列表
        """
        try:
            # 首先测试sessionid状态
            if not self.test_sessionid_status():
                logger.error("[Dreamina] ❌ SessionID验证失败，请检查账号配置")
                return None
                
            # 获取图片尺寸
            width, height = self._get_ratio_dimensions(ratio)
            
            # 生成随机种子，确保在合理范围内
            if seed == -1:
                seed = random.randint(1, 999999999)  
            # 确保用户提供的种子在合理范围内
            seed = max(1, min(seed, 999999999))
            
            # 生成提交ID
            submit_id = str(uuid.uuid4())
            
            # 准备请求数据 - 使用最新API格式
            url = f"{self.base_url}/mweb/v1/aigc_draft/generate"
            
            # 获取模型配置
            model_configs = self.config.get("params", {}).get("models", {})
            model_config = model_configs.get(model)
            
            if not model_config:
                logger.error(f"[Dreamina] 未找到模型配置: {model}")
                logger.error(f"[Dreamina] 可用的模型: {list(model_configs.keys())}")
                return None
                
            # 获取实际的模型请求key
            model_req_key = model_config.get("model_req_key")
            if not model_req_key:
                logger.error(f"[Dreamina] 模型{model}缺少model_req_key配置")
                return None
            
            logger.info(f"[Dreamina] 📋 使用模型: {model} -> {model_req_key}")
            
            # 获取比例值
            ratio_value = self._get_ratio_value(ratio)
            
            # 构建草稿内容 - 使用最新格式
            # 重要：main_component_id和component_list中的id必须相同
            component_id = str(uuid.uuid4())
            
            draft_content = {
                "type": "draft",
                "id": str(uuid.uuid4()),
                "min_version": "3.0.2",
                "min_features": [],
                "is_from_tsn": True,
                "version": "3.3.0",
                "main_component_id": component_id,  # 使用相同的ID
                "component_list": [{
                    "type": "image_base_component",
                    "id": component_id,  # 使用相同的ID
                    "min_version": "3.0.2",
                    "aigc_mode": "workbench",
                    "metadata": {
                        "type": "",
                        "id": str(uuid.uuid4()),
                        "created_platform": 3,
                        "created_platform_version": "",
                        "created_time_in_ms": str(int(time.time() * 1000)),
                        "created_did": ""
                    },
                    "generate_type": "generate",
                    "abilities": {
                        "type": "",
                        "id": str(uuid.uuid4()),
                        "generate": {
                            "type": "",
                            "id": str(uuid.uuid4()),
                            "core_param": {
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "model": model_req_key,
                                "prompt": prompt,
                                "negative_prompt": "",
                                "seed": seed,
                                "sample_strength": 0.5,
                                "image_ratio": ratio_value,
                                "large_image_info": {
                                    "type": "",
                                    "id": str(uuid.uuid4()),
                                    "height": height,
                                    "width": width,
                                    "resolution_type": "1k"
                                },
                                "intelligent_ratio": True
                            }
                        }
                    }
                }]
            }
            
            # 构建metrics_extra数据
            metrics_extra = {
                "promptSource": "user_input",
                "generateCount": 1,
                "templateFrom": "scratch",
                "enterScenario": "workbench",
                "drawType": "draw",
                "impressionId": "",
                "enterFrom": "workbench",
                "templateId": "",
                "templateTypeId": "image",
                "templatePrompt": prompt,
                "generateId": submit_id,
                "isRegenerate": False
            }
            
            # 准备请求数据
            data = {
                "extend": {
                    "root_model": model_req_key
                },
                "submit_id": submit_id,
                "metrics_extra": json.dumps(metrics_extra, ensure_ascii=False),
                "draft_content": json.dumps(draft_content, ensure_ascii=False),
                "http_common_info": {
                    "aid": int(self.aid)
                }
            }
            
            # 构建请求参数
            params = {
                "aid": self.aid,
                "device_platform": "web", 
                "region": "US",
                "da_version": "3.3.0",
                "web_version": "6.6.0",
                "aigc_features": "app_lip_sync",
                "web_component_open_flag": "1"
            }
            
            logger.info(f"[Dreamina] 🎨 开始文生图请求...")
            logger.debug(f"[Dreamina]   - 提交ID: {submit_id}")
            
            # 发送生成请求
            response = self._send_request("POST", url, params=params, json=data)
            
            if not response or response.get("ret") != "0":
                logger.error(f"[Dreamina] ❌ 文生图请求失败")
                return None
                
            # 获取aigc_data信息
            aigc_data = response.get("data", {}).get("aigc_data", {})
            
            # 获取history_id
            history_id = aigc_data.get("history_record_id")
            generate_id = aigc_data.get("generate_id")
            forecast_cost = aigc_data.get("forecast_generate_cost", 0)
            
            if not history_id:
                logger.error("[Dreamina] ❌ 响应中未找到history_id")
                return None
                
            logger.info(f"[Dreamina] ✅ 任务提交成功 (ID: {history_id})")
            logger.debug(f"[Dreamina]   - 生成ID: {generate_id}")
            logger.debug(f"[Dreamina]   - 预估积分消耗: {forecast_cost}")
            
            # 立即检查一次状态 - 使用原始的submit_id查询
            first_check_result = self._get_generated_images(submit_id)
            if first_check_result:
                logger.info("[Dreamina] ✅ 文生图生成完成，无需等待")
                return {"urls": first_check_result, "history_record_id": history_id, "submit_id": submit_id}
            
            # 返回submit_id用于后续查询，history_record_id用于记录
            return {"urls": [], "history_record_id": history_id, "submit_id": submit_id}
            
        except Exception as e:
            logger.error(f"[Dreamina] ❌ 文生图生成异常: {e}")
            import traceback
            logger.error(f"[Dreamina] 详细错误信息: {traceback.format_exc()}")
            return None

    def generate_i2i(self, image: torch.Tensor, prompt: str, model: str, ratio: str, seed: int, num_images: int = 4) -> Tuple[torch.Tensor, str, str]:
        """处理图生图请求"""
        try:
            if not self.token_manager:
                return self._create_error_result("插件未正确初始化，请检查后台日志。")
            
            if not self._is_configured():
                return self._create_error_result("插件未配置，请在 config.json 中至少填入一个账号的 sessionid。")
            
            if not prompt or not prompt.strip():
                return self._create_error_result("提示词不能为空。")

            logger.debug(f"[Dreamina] 开始图生图: {prompt[:50]}...")
            # 兼容多参考图：如果传入的是列表，则走多图上传；否则单图
            if isinstance(image, list):
                result = self.upload_images_and_generate_with_references(
                    images=image,
                    prompt=prompt,
                    model=model,
                    ratio=ratio
                )
                input_image_path = None
            else:
                # 单图流程：先保存临时文件再上传
                input_image_path = self._save_input_image(image)
                if not input_image_path:
                    return self._create_error_result("保存输入图像失败。")
                result = self.upload_image_and_generate_with_reference(
                    image_path=input_image_path,
                    prompt=prompt,
                    model=model,
                    ratio=ratio
                )
            
            if not result:
                return self._create_error_result("API 调用失败，返回为空。请检查网络、防火墙或账号配置。")
            
            # 检查是否是排队模式
            if result.get("is_queued"):
                history_id = result.get("history_id")
                queue_msg = result.get("queue_message", "任务已进入队列，请等待...")
                logger.debug(f"[Dreamina] {queue_msg}")
                
                # 开始轮询等待
                timeout_config = self.config.get("timeout", {})
                max_wait_time = timeout_config.get("max_wait_time", 120)
                check_interval = timeout_config.get("check_interval", 10)
                max_retries = max_wait_time // check_interval
                
                for attempt in range(max_retries):
                    time.sleep(check_interval)
                    res = self._get_generated_images_by_history_id(history_id)
                    # 若网页端拒绝（如 fail_code=1180），立即结束
                    if isinstance(res, dict) and res.get("blocked"):
                        return self._create_error_result(f"网页端拒绝生成: fail_code={res.get('fail_code')}, msg={res.get('fail_msg')}")
                    if isinstance(res, list) and res:
                        urls_to_download = res[:num_images]
                        images = self._download_images(urls_to_download)
                        if not images:
                            return self._create_error_result("下载图片失败，可能链接已失效。")
                        
                        image_batch = torch.cat(images, dim=0)
                        generation_info = self._generate_info_text(prompt, model, ratio, len(images))
                        image_urls_text = "\n\n".join(urls_to_download)
                        
                        # 清理临时文件
                        try:
                            if input_image_path:
                                os.remove(input_image_path)
                        except Exception as e:
                            logger.warning(f"[Dreamina] 清理临时文件失败: {e}")
                            
                        return (image_batch, generation_info, image_urls_text, history_id)
                        
                    # 每30秒输出一次进度日志
                    if (attempt + 1) % 6 == 0:
                        elapsed_time = (attempt + 1) * check_interval
                        logger.debug(f"[Dreamina] 图片生成中... 已等待 {elapsed_time}秒/{max_wait_time}秒")
                
                return self._create_error_result(f"等待图片生成超时，已等待 {max_wait_time}秒")
            
            # 非排队模式，检查是否需要轮询等待
            urls = result.get("urls", [])
            history_id = result.get("history_record_id")
            
            # 如果没有URLs但有history_id，说明任务正在处理中，需要轮询等待
            if not urls and history_id:
                logger.info(f"[Dreamina] 📋 任务正在处理中，开始轮询等待... history_id: {history_id}")
                
                # 开始轮询等待
                timeout_config = self.config.get("timeout", {})
                max_wait_time = timeout_config.get("max_wait_time", 120)
                check_interval = timeout_config.get("check_interval", 10)
                max_retries = max_wait_time // check_interval
                
                for attempt in range(max_retries):
                    time.sleep(check_interval)
                    logger.info(f"[Dreamina] 🔍 检查生成状态... ({attempt + 1}/{max_retries})")
                    
                    res = self._get_generated_images_by_history_id(history_id)
                    # 若网页端拒绝（如 fail_code=1180），立即结束
                    if isinstance(res, dict) and res.get("blocked"):
                        return self._create_error_result(f"网页端拒绝生成: fail_code={res.get('fail_code')}, msg={res.get('fail_msg')}")
                    if isinstance(res, list) and res:
                        logger.info(f"[Dreamina] ✅ 图片生成完成，获取到{len(res)}张图片")
                        urls_to_download = res[:num_images]
                        images = self._download_images(urls_to_download)
                        if not images:
                            return self._create_error_result("下载图片失败，可能链接已失效。")
                        
                        image_batch = torch.cat(images, dim=0)
                        generation_info = self._generate_info_text(prompt, model, ratio, len(images))
                        image_urls_text = "\n\n".join(urls_to_download)
                        
                        # 清理临时文件
                        try:
                            if input_image_path:
                                os.remove(input_image_path)
                        except Exception as e:
                            logger.warning(f"[Dreamina] 清理临时文件失败: {e}")
                            
                        return (image_batch, generation_info, image_urls_text, history_id)
                
                return self._create_error_result(f"等待图片生成超时，已等待 {max_wait_time}秒")
            
            if not urls:
                return self._create_error_result("API未返回图片URL。")
            
            urls_to_download = urls[:num_images]
            images = self._download_images(urls_to_download)
            if not images:
                return self._create_error_result("下载图片失败，可能链接已失效。")
            
            image_batch = torch.cat(images, dim=0)
            generation_info = self._generate_info_text(prompt, model, ratio, len(images))
            image_urls = "\n\n".join(urls_to_download)

            # 清理临时文件
            try:
                if input_image_path:
                    os.remove(input_image_path)
            except Exception as e:
                logger.warning(f"[Dreamina] 清理临时文件失败: {e}")

            logger.debug(f"[Dreamina] 成功生成 {len(images)} 张图片。")
            return (image_batch, generation_info, image_urls, history_id)
            
        except Exception as e:
            logger.exception(f"[Dreamina] 生成图片时发生意外错误")
            return self._create_error_result(f"发生未知错误: {e}")

    def _get_ratio_value(self, ratio: str) -> int:
        """将比例字符串转换为数值
        Args:
            ratio: 比例字符串，如 "4:3"
        Returns:
            int: 比例对应的数值
        """
        # 从配置文件读取正确的ratio_type
        ratios = self.config.get("params", {}).get("ratios", {})
        ratio_config = ratios.get(ratio)
        
        if ratio_config and "ratio_type" in ratio_config:
            ratio_type = ratio_config["ratio_type"]
            logger.debug(f"[Dreamina] 比例映射: {ratio} -> ratio_type: {ratio_type}")
            return ratio_type
        
        # 如果配置中没有找到，使用备用映射（基于curl文件中的正确值）
        fallback_map = {
            "1:1": 1,
            "3:4": 2, 
            "16:9": 3,
            "4:3": 4,
            "9:16": 5,
            "2:3": 6,
            "3:2": 7
        }
        
        ratio_type = fallback_map.get(ratio, 1)
        logger.warning(f"[Dreamina] 配置中未找到比例{ratio}，使用备用映射: ratio_type={ratio_type}")
        return ratio_type

    def _get_ratio_dimensions(self, ratio):
        """获取指定比例的图片尺寸
        Args:
            ratio: 图片比例，如 "1:1", "16:9", "9:16" 等
        Returns:
            tuple: (width, height)
        """
        ratios = self.config.get("params", {}).get("ratios", {})
        ratio_config = ratios.get(ratio)
        
        if not ratio_config:
            # 默认使用 1:1
            return (1024, 1024)
            
        return (ratio_config.get("width", 1024), ratio_config.get("height", 1024))

    def _get_model_key(self, model):
        """获取模型的实际key
        Args:
            model: 模型名称或简写
        Returns:
            str: 模型的实际key
        """
        # 处理简写
        model_map = {
            "20": "2.0",
            "21": "2.1",
            "20p": "2.0p",
            "xlpro": "xl",
            "xl": "xl"
        }
        
        # 如果是简写，转换为完整名称
        if model.lower() in model_map:
            model = model_map[model.lower()]
            
        # 获取模型配置
        models = self.config.get("params", {}).get("models", {})
        if model not in models:
            # 如果模型不存在，使用默认模型
            return self.config.get("params", {}).get("default_model", "3.0")
            
        return model

    def _get_upload_token(self):
        """获取上传token - 使用最新的API端点"""
        try:
            # 使用正确的API端点
            url = "https://mweb-api-sg.capcut.com/artist/v2/tools/get_upload_token"
            
            # 获取token信息
            token_info = self.token_manager.get_token("/artist/v2/tools/get_upload_token")
            if not token_info:
                logger.error("[Dreamina] 无法获取token信息")
                return None
            
            headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
                'appvr': '',
                'content-type': 'application/json',
                'cookie': token_info["cookie"],
                'device-time': token_info["device_time"],
                'lan': 'zh-hans',
                'origin': 'https://dreamina.capcut.com',
                'pf': '1',
                'priority': 'u=1, i',
                'referer': 'https://dreamina.capcut.com/',
                'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Microsoft Edge";v="138"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'sign': token_info["sign"],
                'sign-ver': '1',
                'tdid': 'web',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
            }
            
            # 准备POST请求体
            data = {
                "scene": 2
            }
            
            logger.info("[Dreamina] 🔍 正在获取上传token...")
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"[Dreamina] 获取上传token失败，HTTP状态码: {response.status_code}")
                return None
            
            result = response.json()
            if result.get("ret") != "0":
                logger.error(f"[Dreamina] 获取上传token失败: {result}")
                return None
                
            upload_data = result.get("data", {})
            if not upload_data:
                logger.error("[Dreamina] 上传token响应数据为空")
                return None
            
            logger.info("[Dreamina] ✅ 上传token获取成功")
            return upload_data
            
        except Exception as e:
            logger.error(f"[Dreamina] 获取上传token时发生异常: {e}")
            return None

    def _upload_image(self, image_path, upload_token):
        """上传图片到服务器，使用与视频上传相同的AWS签名方式
        Args:
            image_path: 图片路径
            upload_token: 上传token信息
        Returns:
            str: 上传成功后的图片URI
        """
        try:
            # 获取文件大小
            file_size = os.path.getsize(image_path)
            
            # 第一步：申请图片上传，获取上传地址
            t = datetime.datetime.utcnow()
            amz_date = t.strftime('%Y%m%dT%H%M%SZ')
            
            # 请求参数 - 保持固定顺序
            request_parameters = {
                'Action': 'ApplyImageUpload',
                'Version': '2018-08-01',
                'ServiceId': upload_token.get('space_name', 'fhsjxsyzit'),
                'FileSize': str(file_size),
                's': 'c8nxnei2ek',
                'device_platform': 'web'
            }
            
            # 构建规范请求字符串
            canonical_querystring = '&'.join([f'{k}={urllib.parse.quote(str(v))}' for k, v in sorted(request_parameters.items())])
            
            # 构建规范请求
            canonical_uri = '/'
            canonical_headers = (
                f'host:imagex-normal-sg.capcutapi.com\n'
                f'x-amz-date:{amz_date}\n'
                f'x-amz-security-token:{upload_token.get("session_token", "")}\n'
            )
            signed_headers = 'host;x-amz-date;x-amz-security-token'
            
            # 计算请求体哈希
            payload_hash = hashlib.sha256(b'').hexdigest()
            
            # 构建规范请求
            canonical_request = '\n'.join([
                'GET',
                canonical_uri,
                canonical_querystring,
                canonical_headers,
                signed_headers,
                payload_hash
            ])
            
            # 获取授权头
            authorization = self.get_authorization(
                upload_token.get('access_key_id', ''),
                upload_token.get('secret_access_key', ''),
                'ap-singapore-1',  # 使用正确的区域
                'imagex',
                amz_date,
                upload_token.get('session_token', ''),
                signed_headers,
                canonical_request
            )
            
            # 设置请求头
            headers = {
                'Authorization': authorization,
                'X-Amz-Date': amz_date,
                'X-Amz-Security-Token': upload_token.get('session_token', ''),
                'Host': 'imagex-normal-sg.capcutapi.com'
            }
            
            url = f'https://imagex-normal-sg.capcutapi.com/?{canonical_querystring}'
            
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                logger.error(f"[Dreamina] Failed to get upload authorization: {response.text}")
                return None
                
            upload_info = response.json()
            if not upload_info or "Result" not in upload_info:
                logger.error(f"[Dreamina] No Result in ApplyImageUpload response: {upload_info}")
                return None
            
            # 第二步：上传图片文件
            store_info = upload_info['Result']['UploadAddress']['StoreInfos'][0]
            upload_host = upload_info['Result']['UploadAddress']['UploadHosts'][0]
            
            url = f"https://{upload_host}/upload/v1/{store_info['StoreUri']}"
            
            # 计算文件的CRC32
            with open(image_path, 'rb') as f:
                content = f.read()
                crc32 = format(binascii.crc32(content) & 0xFFFFFFFF, '08x')
            
            headers = {
                'accept': '*/*',
                'authorization': store_info['Auth'],
                'content-type': 'application/octet-stream',
                'content-disposition': 'attachment; filename="undefined"',
                'content-crc32': crc32,
                'origin': 'https://mweb-api-sg.capcut.com',
                'referer': 'https://mweb-api-sg.capcut.com/'
            }
            
            response = requests.post(url, headers=headers, data=content)
            if response.status_code != 200:
                logger.error(f"[Dreamina] Failed to upload image: {response.text}")
                return None
                
            upload_result = response.json()
            if upload_result.get("code") != 2000:
                logger.error(f"[Dreamina] Upload image error: {upload_result}")
                return None
            
            # 第三步：提交上传，确认图片
            session_key = upload_info['Result']['UploadAddress']['SessionKey']
            store_uri = store_info.get("StoreUri", "")
            
            amz_date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            
            params = {
                "Action": "CommitImageUpload",
                "Version": "2018-08-01",
                "ServiceId": upload_token.get('space_name', 'fhsjxsyzit')
            }
            
            data = {
                "SessionKey": session_key
            }
            
            payload = json.dumps(data)
            content_sha256 = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            
            # 构建规范请求
            canonical_uri = "/"
            canonical_querystring = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
            signed_headers = "x-amz-content-sha256;x-amz-date;x-amz-security-token"
            canonical_headers = f"x-amz-content-sha256:{content_sha256}\nx-amz-date:{amz_date}\nx-amz-security-token:{upload_token.get('session_token', '')}\n"
            
            canonical_request = f"POST\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{content_sha256}"
            
            authorization = self.get_authorization(
                upload_token.get('access_key_id', ''),
                upload_token.get('secret_access_key', ''),
                'ap-singapore-1',  # 使用正确的区域
                'imagex',
                amz_date,
                upload_token.get('session_token', ''),
                signed_headers,
                canonical_request
            )
            
            headers = {
                'accept': '*/*',
                'content-type': 'application/json',
                'authorization': authorization,
                'x-amz-content-sha256': content_sha256,
                'x-amz-date': amz_date,
                'x-amz-security-token': upload_token.get('session_token', ''),
                'origin': 'https://dreamina.capcut.com',
                'referer': 'https://dreamina.capcut.com/'
            }
            
            commit_url = "https://imagex-normal-sg.capcutapi.com"
            response = requests.post(f"{commit_url}?{canonical_querystring}", headers=headers, data=payload)
            if response.status_code != 200:
                logger.error(f"[Dreamina] Failed to commit upload: {response.text}")
                return None
                
            commit_result = response.json()
            if not commit_result or "Result" not in commit_result:
                logger.error(f"[Dreamina] No Result in CommitImageUpload response: {commit_result}")
                return None
                
            # 返回图片URI
            return store_uri
            
        except Exception as e:
            logger.error(f"[Dreamina] Error uploading image: {e}")
            return None

    def _verify_uploaded_image(self, image_uri):
        """验证上传的图片"""
        try:
            url = f"{self.base_url}/mweb/v1/algo_proxy"
            params = {
                "babi_param": json.dumps({
                    "scenario": "image_video_generation",
                    "feature_key": "aigc_to_image",
                    "feature_entrance": "to_image",
                    "feature_entrance_detail": "to_image-algo_proxy"
                }),
                "needCache": "true",
                "cacheErrorCodes[]": "2203",
                "aid": self.aid,
                "device_platform": "web",
                "region": "HK",
                "web_id": self.token_manager.get_web_id(),
                "da_version": "3.1.5"
            }
            
            data = {
                "scene": "image_face_ip",
                "options": {"ip_check": True},
                "req_key": "benchmark_test_user_upload_image_input",
                "file_list": [{"file_uri": image_uri}],
                "req_params": {}
            }
            
            response = self._send_request("POST", url, params=params, json=data)
            return response and response.get("ret") == "0"
            
        except Exception as e:
            logger.error(f"[Dreamina] Error verifying uploaded image: {e}")
            return False

    def _get_image_description(self, image_uri):
        """获取图片描述"""
        try:
            url = f"{self.base_url}/mweb/v1/get_image_description"
            params = {
                "babi_param": json.dumps({
                    "scenario": "image_video_generation",
                    "feature_key": "aigc_to_image",
                    "feature_entrance": "to_image",
                    "feature_entrance_detail": "to_image-get_image_description"
                }),
                "needCache": "false",
                "aid": self.aid,
                "device_platform": "web",
                "region": "HK",
                "web_id": self.token_manager.get_web_id(),
                "da_version": "3.1.5"
            }
            
            data = {
                "file_uri": image_uri
            }
            
            response = self._send_request("POST", url, params=params, json=data)
            if response and response.get("ret") == "0":
                return response.get("data", {}).get("description", "")
            
            return ""
            
        except Exception as e:
            logger.error(f"[Dreamina] Error getting image description: {e}")
            return ""

    def upload_image_and_generate_with_reference(self, image_path, prompt, model="3.0", ratio="1:1"):
        """上传参考图并生成新图片
        Args:
            image_path: 参考图片路径
            prompt: 提示词
            model: 模型名称
            ratio: 图片比例
        Returns:
            dict: 包含生成的图片URL列表
        """
        try:
            # 获取图片尺寸
            width, height = self._get_ratio_dimensions(ratio)
            
            # 获取上传token
            upload_token = self._get_upload_token()
            if not upload_token:
                logger.error("[Dreamina] Failed to get upload token")
                return None
                
            # 上传图片
            image_uri = self._upload_image(image_path, upload_token)
            if not image_uri:
                logger.error("[Dreamina] Failed to upload image")
                return None
                
            # 图片URI验证
            self._verify_uploaded_image(image_uri)
            
            logger.info(f"[Dreamina] 图片上传成功, URI: {image_uri}")
            
            # 获取模型配置
            models = self.config.get("params", {}).get("models", {})
            model_info = models.get(model, {})
            
            if not model_info:
                logger.error(f"[Dreamina] 图生图未找到模型配置: {model}")
                logger.error(f"[Dreamina] 可用的模型: {list(models.keys())}")
                return None
            
            # 获取实际的模型请求key
            model_req_key = model_info.get("model_req_key")
            if not model_req_key:
                logger.error(f"[Dreamina] 模型{model}缺少model_req_key配置")
                # 使用默认的3.0模型作为备用
                model_req_key = "high_aes_general_v30l:general_v3.0_18b"
                logger.warning(f"[Dreamina] 使用默认模型key: {model_req_key}")
            
            logger.info(f"[Dreamina] 📋 图生图使用模型: {model} -> {model_req_key}")
            
            # 准备请求参数
            submit_id = str(uuid.uuid4())
            draft_id = str(uuid.uuid4())
            component_id = str(uuid.uuid4())
            
            # 准备data（使用最新的API格式）
            draft_content = {
                "type": "draft",
                "id": draft_id,
                "min_version": "3.0.2",
                "min_features": [],
                "is_from_tsn": True,
                "version": "3.3.0",
                "main_component_id": component_id,
                "component_list": [{
                    "type": "image_base_component",
                    "id": component_id,
                    "min_version": "3.0.2",
                    "aigc_mode": "workbench",
                    "metadata": {
                        "type": "",
                        "id": str(uuid.uuid4()),
                        "created_platform": 3,
                        "created_platform_version": "",
                        "created_time_in_ms": str(int(time.time() * 1000)),
                        "created_did": ""
                    },
                    "generate_type": "blend",
                    "abilities": {
                        "type": "",
                        "id": str(uuid.uuid4()),
                        "blend": {
                            "type": "",
                            "id": str(uuid.uuid4()),
                            "min_version": "3.0.2",
                            "min_features": [],
                            "core_param": {
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "model": model_req_key,
                                "prompt": f"##{prompt}",
                                "sample_strength": 0.5,
                                "image_ratio": self._get_ratio_value(ratio),
                                "large_image_info": {
                                    "type": "",
                                    "id": str(uuid.uuid4()),
                                    "height": height,
                                    "width": width,
                                    "resolution_type": "1k"
                                },
                                "intelligent_ratio": True
                            },
                            "ability_list": [{
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "name": "byte_edit",
                                "image_uri_list": [image_uri],
                                "image_list": [{
                                    "type": "image",
                                    "id": str(uuid.uuid4()),
                                    "source_from": "upload",
                                    "platform_type": 1,
                                    "name": "",
                                    "image_uri": image_uri,
                                    "width": 0,
                                    "height": 0,
                                    "format": "",
                                    "uri": image_uri
                                }],
                                "strength": 0.5
                            }],
                            "history_option": {
                                "type": "",
                                "id": str(uuid.uuid4())
                            },
                            "prompt_placeholder_info_list": [{
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "ability_index": 0
                            }],
                            "postedit_param": {
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "generate_type": 0
                            }
                        }
                    }
                }]
            }
            
            # 添加draft_content调试日志
            logger.debug(f"[Dreamina] draft_content结构:")
            logger.debug(f"[Dreamina] - draft_id: {draft_id}")
            logger.debug(f"[Dreamina] - component_id: {component_id}")
            logger.debug(f"[Dreamina] - image_uri: {image_uri}")
            logger.debug(f"[Dreamina] - image_ratio: {self._get_ratio_value(ratio)}")
            logger.debug(f"[Dreamina] - large_image_info: {width}x{height}")
            
            # 准备请求数据 - 使用最新的API格式
            url = f"{self.base_url}/mweb/v1/aigc_draft/generate"
            
            # 构建metrics_extra数据
            metrics_extra = {
                "promptSource": "custom",
                "generateCount": 1,
                "enterFrom": "click",
                "generateId": submit_id,
                "isRegenerate": False
            }
            
            data = {
                "extend": {
                    "root_model": model_req_key
                },
                "submit_id": submit_id,
                "metrics_extra": json.dumps(metrics_extra, ensure_ascii=False),
                "draft_content": json.dumps(draft_content, ensure_ascii=False),
                "http_common_info": {
                    "aid": int(self.aid)
                }
            }
            
            params = {
                "aid": self.aid,
                "device_platform": "web",
                "region": "US",
                "da_version": "3.3.0",
                "web_version": "6.6.0",
                "aigc_features": "app_lip_sync",
                "web_component_open_flag": "1"
            }
            
            # 添加调试日志
            logger.info(f"[Dreamina] 发送图生图请求:")
            logger.info(f"[Dreamina] URL: {url}")
            logger.info(f"[Dreamina] 模型: {model_req_key}")
            logger.info(f"[Dreamina] 提示词: {prompt}")
            logger.info(f"[Dreamina] 图片URI: {image_uri}")
            logger.info(f"[Dreamina] 比例: {ratio}")
            logger.info(f"[Dreamina] 尺寸: {width}x{height}")
            
            # 添加完整请求数据调试日志
            logger.debug(f"[Dreamina] 完整请求数据:")
            logger.debug(f"[Dreamina] Params: {json.dumps(params, indent=2, ensure_ascii=False)}")
            logger.debug(f"[Dreamina] Data: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            # 添加请求头调试日志
            headers = self._get_headers("/mweb/v1/aigc_draft/generate")
            logger.debug(f"[Dreamina] 请求头:")
            logger.debug(f"[Dreamina] Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}")
            
            # 发送生成请求
            response = self._send_request("POST", url, params=params, json=data)
            
            if not response or response.get("ret") != "0":
                logger.error(f"[Dreamina] Failed to generate image with reference: {response}")
                # 添加更详细的错误信息
                if response:
                    logger.error(f"[Dreamina] 错误详情: ret={response.get('ret')}, errmsg={response.get('errmsg')}")
                    logger.error(f"[Dreamina] 完整响应: {json.dumps(response, indent=2, ensure_ascii=False)}")
                return None
                
            # 获取aigc_data信息
            aigc_data = response.get("data", {}).get("aigc_data", {})
            
            # 获取history_id 和 history_group_key_md5
            history_id = aigc_data.get("history_record_id")
            history_group_key_md5 = aigc_data.get("history_group_key_md5")
            
            if not history_id:
                logger.error("[Dreamina] No history_id in response")
                return None
                
            logger.info(f"[Dreamina] 请求成功，history_id: {history_id}")
            
            # 从配置文件读取超时参数（参考图生成）
            timeout_config = self.config.get("timeout", {})
            max_wait_time = timeout_config.get("max_wait_time", 120)  # 默认2分钟
            check_interval = timeout_config.get("check_interval", 10)  # 默认10秒间隔
            
            # 立即获取一次状态，检查排队信息
            first_check_result = self._get_generated_images_by_history_id(history_id)
            queue_info = self._get_queue_info_from_response(history_id)
            
            # 如果有排队信息且图片未生成完成，立即返回排队信息
            if queue_info and not first_check_result:
                queue_msg = self._format_queue_message(queue_info)
                # 立即返回排队信息，让用户知道需要等待多久
                return {
                    "is_queued": True,
                    "queue_message": queue_msg,
                    "history_id": history_id
                }
            
            if first_check_result:
                logger.info("[Dreamina] 参考图生成成功，无需等待")
                return {"urls": first_check_result, "history_record_id": history_id}
            
            return {"urls": [], "history_record_id": history_id}
            
        except Exception as e:
            logger.error(f"[Dreamina] Error generating image with reference: {e}")
            return None

    def upload_images_and_generate_with_references(self, images: List[torch.Tensor], prompt, model="3.0", ratio="1:1"):
        """上传多张参考图并生成新图片（最多6张）
        Args:
            images: 参考图张量列表
            prompt: 提示词
            model: 模型名称
            ratio: 图片比例
        Returns:
            dict: 包含生成的图片URL列表/排队信息
        """
        try:
            # 获取图片尺寸
            width, height = self._get_ratio_dimensions(ratio)

            # 获取上传token（一次，多图复用）
            upload_token = self._get_upload_token()
            if not upload_token:
                logger.error("[Dreamina] Failed to get upload token")
                return None

            # 逐张保存并上传
            image_paths = []
            image_uris = []
            for idx, tensor in enumerate(images[:6]):
                path = self._save_input_image(tensor)
                if not path:
                    logger.error(f"[Dreamina] 第{idx+1}张参考图保存失败")
                    continue
                image_paths.append(path)
                uri = self._upload_image(path, upload_token)
                if not uri:
                    logger.error(f"[Dreamina] 第{idx+1}张参考图上传失败")
                    continue
                image_uris.append(uri)

            if not image_uris:
                return None

            logger.info(f"[Dreamina] 多参考图上传成功, 数量: {len(image_uris)}")

            # 模型key
            models = self.config.get("params", {}).get("models", {})
            model_info = models.get(model, {})
            if not model_info:
                logger.error(f"[Dreamina] 图生图未找到模型配置: {model}")
                return None
            model_req_key = model_info.get("model_req_key") or "high_aes_general_v30l:general_v3.0_18b"

            logger.info(f"[Dreamina] 📋 图生图使用模型: {model} -> {model_req_key}")

            # 组装 ability 的 image_list 与 image_uri_list
            image_list = [{
                "type": "image",
                "id": str(uuid.uuid4()),
                "source_from": "upload",
                "platform_type": 1,
                "name": "",
                "image_uri": uri,
                "width": 0,
                "height": 0,
                "format": "",
                "uri": uri
            } for uri in image_uris]

            submit_id = str(uuid.uuid4())
            draft_id = str(uuid.uuid4())
            component_id = str(uuid.uuid4())

            draft_content = {
                "type": "draft",
                "id": draft_id,
                "min_version": "3.0.2",
                "min_features": [],
                "is_from_tsn": True,
                "version": "3.3.0",
                "main_component_id": component_id,
                "component_list": [{
                    "type": "image_base_component",
                    "id": component_id,
                    "min_version": "3.0.2",
                    "aigc_mode": "workbench",
                    "metadata": {
                        "type": "",
                        "id": str(uuid.uuid4()),
                        "created_platform": 3,
                        "created_platform_version": "",
                        "created_time_in_ms": str(int(time.time() * 1000)),
                        "created_did": ""
                    },
                    "generate_type": "blend",
                    "abilities": {
                        "type": "",
                        "id": str(uuid.uuid4()),
                        "blend": {
                            "type": "",
                            "id": str(uuid.uuid4()),
                            "min_version": "3.0.2",
                            "min_features": [],
                            "core_param": {
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "model": model_req_key,
                                "prompt": f"##{prompt}",
                                "sample_strength": 0.5,
                                "image_ratio": self._get_ratio_value(ratio),
                                "large_image_info": {
                                    "type": "",
                                    "id": str(uuid.uuid4()),
                                    "height": height,
                                    "width": width,
                                    "resolution_type": "1k"
                                },
                                "intelligent_ratio": True
                            },
                            "ability_list": [{
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "name": "byte_edit",
                                "image_uri_list": image_uris,
                                "image_list": image_list,
                                "strength": 0.5
                            }],
                            "history_option": {
                                "type": "",
                                "id": str(uuid.uuid4())
                            },
                            "prompt_placeholder_info_list": [{
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "ability_index": 0
                            }],
                            "postedit_param": {
                                "type": "",
                                "id": str(uuid.uuid4()),
                                "generate_type": 0
                            }
                        }
                    }
                }]
            }

            url = f"{self.base_url}/mweb/v1/aigc_draft/generate"
            metrics_extra = {
                "promptSource": "custom",
                "generateCount": 1,
                "enterFrom": "click",
                "generateId": submit_id,
                "isRegenerate": False
            }
            data = {
                "extend": {"root_model": model_req_key},
                "submit_id": submit_id,
                "metrics_extra": json.dumps(metrics_extra, ensure_ascii=False),
                "draft_content": json.dumps(draft_content, ensure_ascii=False),
                "http_common_info": {"aid": int(self.aid)}
            }
            params = {
                "aid": self.aid,
                "device_platform": "web",
                "region": "US",
                "da_version": "3.3.0",
                "web_version": "6.6.0",
                "aigc_features": "app_lip_sync",
                "web_component_open_flag": "1"
            }

            logger.info(f"[Dreamina] 发送多参考图生图请求, 数量: {len(image_uris)}")
            response = self._send_request("POST", url, params=params, json=data)
            # 清理临时文件
            for p in image_paths:
                try:
                    os.remove(p)
                except Exception:
                    pass

            if not response or response.get("ret") != "0":
                logger.error(f"[Dreamina] Failed to generate image with references: {response}")
                if response:
                    logger.error(f"[Dreamina] 错误详情: ret={response.get('ret')}, errmsg={response.get('errmsg')}")
                return None

            aigc_data = response.get("data", {}).get("aigc_data", {})
            history_id = aigc_data.get("history_record_id")
            if not history_id:
                logger.error("[Dreamina] No history_id in response")
                return None

            logger.info(f"[Dreamina] 请求成功，history_id: {history_id}")

            first_check_result = self._get_generated_images_by_history_id(history_id)
            queue_info = self._get_queue_info_from_response(history_id)
            if queue_info and not first_check_result:
                queue_msg = self._format_queue_message(queue_info)
                return {"is_queued": True, "queue_message": queue_msg, "history_id": history_id}

            if first_check_result:
                logger.info("[Dreamina] 多参考图生成成功，无需等待")
                return {"urls": first_check_result, "history_record_id": history_id}

            return {"urls": [], "history_record_id": history_id}
        except Exception as e:
            logger.error(f"[Dreamina] Error generating image with references: {e}")
            return None

    def _get_generated_images(self, submit_id):
        """通过提交ID获取生成的图片(文生图)，使用最新API格式"""
        try:
            url = f"{self.base_url}/mweb/v1/get_history_by_ids"
            
            # 使用最新的API参数格式
            params = {
                "aid": self.aid,
                "device_platform": "web",
                "region": "US",
                "da_version": "3.2.8",
                "web_version": "6.6.0",
                "aigc_features": "app_lip_sync"
            }
            
            # 使用最新的请求数据格式 - 使用submit_id查询
            data = {
                "submit_ids": [submit_id]
            }
            
            logger.debug(f"[Dreamina] 🔍 查询生成结果: submit_id={submit_id}")
            
            result = self._send_request("POST", url, params=params, json=data)
            
            if not result or result.get("ret") != "0":
                logger.error(f"[Dreamina] ❌ 获取生成状态失败")
                return None
                
            # 解析最新的响应格式 - 响应中的key是submit_id
            history_data = result.get("data", {}).get(submit_id, {})
            if not history_data:
                logger.debug(f"[Dreamina] ⏳ 任务数据尚未就绪")
                return None
            
            # 检查任务状态
            task = history_data.get("task", {})
            task_status = task.get("status", 0)
            
            logger.debug(f"[Dreamina] 📈 任务状态: {task_status}")
            
            # 检查失败状态 - 只有非零的fail_code才表示失败
            fail_code = history_data.get("fail_code", "")
            fail_starling_message = history_data.get("fail_starling_message", "")
            
            # fail_code为"0"或空字符串表示成功，只有非零值才是失败
            if fail_code and fail_code != "" and fail_code != "0":
                logger.error(f"[Dreamina] ❌ 任务失败:")
                logger.error(f"[Dreamina]   - 失败代码: {fail_code}")
                logger.error(f"[Dreamina]   - 失败信息: {fail_starling_message}")
                return None
            
            # 状态码50表示任务成功完成
            if task_status == 50:
                logger.info(f"[Dreamina] ✅ 任务完成，解析图片URL")
                image_urls = []
                
                # 从item_list中提取图片URL
                item_list = history_data.get("item_list", [])
                
                if item_list:
                    logger.debug(f"[Dreamina] 🖼️ 找到{len(item_list)}个生成的图片")
                    for i, item in enumerate(item_list):
                        # 优先从image.large_images获取高质量图片
                        image = item.get("image", {})
                        large_images = image.get("large_images", [])
                        
                        if large_images:
                            for j, large_image in enumerate(large_images):
                                image_url = large_image.get("image_url")
                                if image_url:
                                    image_urls.append(image_url)
                                    width = large_image.get("width", 0)
                                    height = large_image.get("height", 0)
                                    format_type = large_image.get("format", "unknown")
                                    logger.debug(f"[Dreamina] ✅ 图片{i+1}: {width}x{height} {format_type}")
                        
                        # 备用方案：从common_attr获取封面图
                        if not large_images:
                            common_attr = item.get("common_attr", {})
                            cover_url = common_attr.get("cover_url")
                            if cover_url:
                                image_urls.append(cover_url)
                                logger.debug(f"[Dreamina] ✅ 备用图片{i+1}")
                
                if image_urls:
                    logger.info(f"[Dreamina] ✅ 获取到{len(image_urls)}个图片URL")
                    return image_urls
                else:
                    logger.error("[Dreamina] ❌ 未找到任何图片URL")
                    return None
                    
            else:
                # 其他状态码表示任务未完成
                if task_status == 20:
                    logger.debug(f"[Dreamina] ⏳ 任务进行中")
                else:
                    logger.debug(f"[Dreamina] ⏳ 任务状态: {task_status}")
                return None
                
        except Exception as e:
            logger.error(f"[Dreamina] ❌ 查询生成结果时发生异常: {e}")
            import traceback
            logger.error(f"[Dreamina] 详细错误信息: {traceback.format_exc()}")
            return None

    def _get_generated_images_by_history_id(self, history_id):
        """通过历史ID获取生成的图片
        Args:
            history_id: 历史ID
        Returns:
            list: 图片URL列表
        """
        try:
            url = f"{self.base_url}/mweb/v1/get_history_by_ids"
            
            params = {
                "aid": self.aid,
                "device_platform": "web",
                "region": "US",
                "web_id": self.token_manager.get_web_id()
            }
            
            # 使用与成功的curl请求一致的参数结构
            data = {
                "history_ids": [history_id],
                "image_info": {
                    "width": 2048,
                    "height": 2048,
                    "format": "webp",
                    "image_scene_list": [
                        {"scene": "normal", "width": 2400, "height": 2400, "uniq_key": "2400", "format": "webp"},
                        {"scene": "loss", "width": 1080, "height": 1080, "uniq_key": "1080", "format": "webp"},
                        {"scene": "loss", "width": 720, "height": 720, "uniq_key": "720", "format": "webp"},
                        {"scene": "loss", "width": 480, "height": 480, "uniq_key": "480", "format": "webp"},
                        {"scene": "loss", "width": 360, "height": 360, "uniq_key": "360", "format": "webp"}
                    ]
                }
            }

            
            result = self._send_request("POST", url, params=params, json=data)
            
            if not result or result.get("ret") != "0":
                logger.error(f"[Dreamina] 获取生成状态失败: {result}")
                return None
                
            # 获取历史记录数据
            history_data = result.get("data", {}).get(history_id, {})
            if not history_data:
                return None
            
            # 检查失败状态 - 只有非零的fail_code才表示失败
            fail_code = history_data.get("fail_code", "")
            fail_msg = history_data.get("fail_msg", "")
            
            # fail_code为"0"或空字符串表示成功，只有非零值才是失败
            if fail_code and fail_code != "" and fail_code != "0":
                logger.error(f"[Dreamina] ❌ 任务失败: fail_code={fail_code}, fail_msg={fail_msg}")
                # 特殊处理：1180 表示网页端拒绝，直接通知上层停止轮询
                if str(fail_code) == "1180":
                    return {"blocked": True, "fail_code": str(fail_code), "fail_msg": fail_msg}
                return None
                
            status = history_data.get("status")
            
            # 使用正确的状态码检测
            if status == 50:  # 任务成功完成
                resources = history_data.get("resources", [])
                draft_content = history_data.get("draft_content", "")
                
                if not resources:
                    logger.error("[Dreamina] 未找到资源数据")
                    return None
                
                # 解析draft_content以获取所有原始上传图片的URI（多参考图需要全部排除）
                upload_image_uris = set()
                try:
                    draft_content_dict = json.loads(draft_content)
                    component_list = draft_content_dict.get("component_list", [])
                    for component in component_list:
                        abilities = component.get("abilities", {})
                        blend_data = abilities.get("blend", {})
                        ability_list = blend_data.get("ability_list", [])
                        for ability in ability_list:
                            if ability.get("name") == "byte_edit":
                                # 收集 image_uri_list 中的所有上传原图 URI
                                image_uri_list = ability.get("image_uri_list", [])
                                for uri in image_uri_list:
                                    if uri:
                                        upload_image_uris.add(uri)
                                # 额外收集 image_list 中的 uri（有些返回只在这里提供）
                                for img in ability.get("image_list", []):
                                    uri2 = (img or {}).get("uri")
                                    if uri2:
                                        upload_image_uris.add(uri2)
                except Exception as e:
                    logger.error(f"[Dreamina] 解析draft_content失败: {e}")
                    
                # 从resources中提取图片URL，排除原始上传图片
                image_urls = []
                for resource in resources:
                    if resource.get("type") == "image":
                        image_info = resource.get("image_info", {})
                        # 优先使用 ori_key 作为上传原图标识；其次使用 image_orig_url；最后回退到 key
                        resource_uri = resource.get("ori_key") or image_info.get("image_orig_url") or resource.get("key")
                        image_url = image_info.get("image_url")
                        
                        # 过滤掉所有上传的原图（支持多参考图），仅保留生成结果
                        if (not resource_uri or resource_uri not in upload_image_uris) and image_url:
                            image_urls.append(image_url)
                
                # 如果从resources中找不到生成的图片，尝试从item_list中获取
                if not image_urls:
                    item_list = history_data.get("item_list", [])
                    for item in item_list:
                        image = item.get("image", {})
                        if image and "large_images" in image:
                            for large_image in image["large_images"]:
                                image_url = large_image.get("image_url")
                                if image_url:
                                    image_urls.append(image_url)
                        elif image and image.get("image_url"):
                            image_urls.append(image["image_url"])

                if image_urls:
                    logger.info(f"[Dreamina] ✅ 获取到 {len(image_urls)} 个图片URL。")
                    return image_urls
                else:
                    logger.error("[Dreamina] 未找到生成的图片URL")
                    return None
                
            elif status == 30:  # 任务失败
                logger.error(f"[Dreamina] ❌ 任务失败，状态: {status}")
                logger.error(f"[Dreamina] 📊 失败详情: fail_code={fail_code}, fail_msg={fail_msg}")
                return None
            elif status == 20:  # 任务处理中
                logger.info(f"[Dreamina] ⏳ 任务仍在处理中，状态: {status}")
                return None
            else:
                logger.info(f"[Dreamina] ⏳ 任务状态未知: {status}")
                return None
                
        except Exception as e:
            logger.error(f"[Dreamina] 检查生成状态时发生意外错误: {e}", exc_info=True)
            return None

    def _get_queue_info_from_response(self, history_id):
        """从API响应中获取排队信息"""
        try:
            url = f"{self.base_url}/mweb/v1/get_history_by_ids"
            
            params = {
                "aid": self.aid,
                "device_platform": "web",
                "region": "US",
                "web_id": self.token_manager.get_web_id()
            }
            
            data = {
                "history_ids": [history_id],
                "image_info": {
                    "width": 2048,
                    "height": 2048,
                    "format": "webp",
                    "image_scene_list": [
                        {"scene": "normal", "width": 2400, "height": 2400, "uniq_key": "2400", "format": "webp"},
                        {"scene": "normal", "width": 1080, "height": 1080, "uniq_key": "1080", "format": "webp"}
                    ]
                },
                "http_common_info": {"aid": self.aid}
            }
            
            result = self._send_request("POST", url, params=params, json=data)
            
            if result and result.get('ret') == '0':
                history_data = result.get('data', {}).get(history_id, {})
                queue_info = history_data.get('queue_info', {})
                if queue_info:
                    return queue_info
                return None
                
        except Exception as e:
            logger.error(f"[Dreamina] Error getting queue info: {e}")
            return None

    def _format_queue_message(self, queue_info):
        """格式化排队信息为用户友好的消息"""
        try:
            queue_idx = queue_info.get('queue_idx', 0)
            queue_length = queue_info.get('queue_length', 0)
            queue_status = queue_info.get('queue_status', 0)
            
            # 获取真正的等待时间阈值
            priority_queue_display_threshold = queue_info.get('priority_queue_display_threshold', {})
            waiting_time_threshold = priority_queue_display_threshold.get('waiting_time_threshold', 0)
            
            # 将waiting_time_threshold从秒转换为分钟
            wait_minutes = waiting_time_threshold // 60
            wait_seconds = waiting_time_threshold % 60
            
            if wait_minutes > 0:
                time_str = f"{wait_minutes}分{wait_seconds}秒" if wait_seconds > 0 else f"{wait_minutes}分钟"
            else:
                time_str = f"{wait_seconds}秒"
            
            if queue_status == 1:  # 正在排队
                if queue_idx > 0 and queue_length > 0:
                    return f"📊 总队列长度：{queue_length}人\n🔄 您的位置：第{queue_idx}位\n⏰ 预计等待时间：{time_str}\n\n图片正在排队生成中，请耐心等待..."
                else:
                    return f"🔄 图片生成任务已提交，预计等待时间：{time_str}"
            else:
                return "🚀 当前无需排队，正在使用快速生成模式，请等待片刻..."
                
        except Exception as e:
            logger.error(f"[Dreamina] Error formatting queue message: {e}")
            return "🔄 图片生成任务正在排队处理中，请稍候..." 

    def get_authorization(self, access_key, secret_key, region, service, amz_date, security_token, signed_headers, canonical_request):
        """获取AWS V4签名授权头
        Args:
            access_key: 访问密钥ID
            secret_key: 密钥
            region: 地区
            service: 服务名
            amz_date: 日期时间
            security_token: 安全令牌
            signed_headers: 已签名的头部
            canonical_request: 规范请求
        Returns:
            str: 授权头
        """
        try:
            datestamp = amz_date[:8]
            
            # 计算规范请求的哈希值
            canonical_request_hash = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
            
            # 构建待签名字符串
            credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
            string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{canonical_request_hash}"
            
            # 计算签名密钥
            k_date = hmac.new(f"AWS4{secret_key}".encode('utf-8'), datestamp.encode('utf-8'), hashlib.sha256).digest()
            k_region = hmac.new(k_date, region.encode('utf-8'), hashlib.sha256).digest()
            k_service = hmac.new(k_region, service.encode('utf-8'), hashlib.sha256).digest()
            k_signing = hmac.new(k_service, b'aws4_request', hashlib.sha256).digest()
            
            # 计算签名
            signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
            
            # 构建授权头
            authorization = (
                f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            )
            
            return authorization
        except Exception as e:
            logger.error(f"[Dreamina] Error generating authorization: {str(e)}")
            return ""

    def _create_error_result(self, error_msg: str) -> Tuple[torch.Tensor, str, str]:
        """创建错误结果
        Args:
            error_msg: 错误信息
        Returns:
            Tuple[torch.Tensor, str, str]: (错误图像, 错误信息, 空URL列表)
        """
        logger.error(f"[Dreamina] {error_msg}")
        error_image = torch.ones(1, 256, 256, 3) * torch.tensor([1.0, 0.0, 0.0])
        return (error_image, f"错误: {error_msg}", "")

    def _download_images(self, urls: List[str]) -> List[torch.Tensor]:
        """下载图片并转换为张量
        Args:
            urls: 图片URL列表
        Returns:
            List[torch.Tensor]: 图片张量列表
        """
        images = []
        for url in urls:
            try:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                img_data = response.content
                
                pil_image = Image.open(io.BytesIO(img_data)).convert("RGB")
                np_image = np.array(pil_image, dtype=np.float32) / 255.0
                tensor_image = torch.from_numpy(np_image).unsqueeze(0)
                images.append(tensor_image)
            except Exception as e:
                logger.error(f"[Dreamina] 下载或处理图片失败 {url}: {e}")
                continue
        return images

    def _save_input_image(self, image_tensor: torch.Tensor) -> Optional[str]:
        """将输入的图像张量保存为临时文件
        Args:
            image_tensor: 输入图像张量
        Returns:
            str: 临时文件路径，如果保存失败则返回None
        """
        try:
            # 确保临时目录存在
            temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp")
            os.makedirs(temp_dir, exist_ok=True)
            
            # 生成临时文件路径
            temp_path = os.path.join(temp_dir, f"temp_input_{int(time.time())}.png")
            
            # 将张量转换为PIL图像并保存
            if len(image_tensor.shape) == 4:  # batch, height, width, channels
                image_tensor = image_tensor[0]  # 取第一张图片
            
            # 确保值在0-1范围内
            image_tensor = torch.clamp(image_tensor, 0, 1)
            
            # 转换为PIL图像
            image_np = (image_tensor.cpu().numpy() * 255).astype(np.uint8)
            image_pil = Image.fromarray(image_np)
            
            # 保存图像
            image_pil.save(temp_path)
            logger.info(f"[Dreamina] 输入图像已保存到: {temp_path}")
            
            return temp_path
        except Exception as e:
            logger.error(f"[Dreamina] 保存输入图像失败: {e}")
            return None

    def _generate_info_text(self, prompt: str, model: str, ratio: str, num_images: int) -> str:
        """生成图片信息文本
        Args:
            prompt: 提示词
            model: 模型名称
            ratio: 图片比例
            num_images: 图片数量
        Returns:
            str: 信息文本
        """
        models_config = self.config.get("params", {}).get("models", {})
        model_display_name = models_config.get(model, {}).get("name", model)
        
        info_lines = [f"提示词: {prompt}", f"模型: {model_display_name}", f"比例: {ratio}", f"数量: {num_images}"]
        return "\n".join(info_lines)

    def _is_configured(self) -> bool:
        """检查配置是否包含至少一个有效的sessionid。"""
        accounts = self.config.get("accounts", [])
        if not isinstance(accounts, list) or not accounts:
            return False
        return any(acc.get("sessionid") for acc in accounts)

    def test_sessionid_status(self):
        """测试当前sessionid的状态"""
        try:
            logger.info(f"[Dreamina] 🔍 跳过SessionID验证，直接使用配置的SessionID")
            return True
                
        except Exception as e:
            logger.error(f"[Dreamina] ❌ 测试SessionID时出错: {e}")
            return False