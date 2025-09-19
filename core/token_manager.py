import requests
import json
import os
import random
import hashlib
import time
from typing import Dict, Any, Optional, List
import logging
import datetime

logger = logging.getLogger(__name__)

class TokenManager:
    def __init__(self, config):
        self.config = config
        self.accounts = config.get("accounts", [])
        self.current_account_index = 0
        self.version_code = "5.8.0"
        self.platform_code = "7"
        self.device_id = str(random.random() * 999999999999999999 + 7000000000000000000)
        self.web_id = str(random.random() * 999999999999999999 + 7000000000000000000)
        self.user_id = str(random.random() * 999999999999999999 + 7000000000000000000) # Changed to generate a random user_id
        
        logger.info(f"[Dreamina] Initialized with {len(self.accounts)} accounts")
        
        # 初始化时为每个账号生成一个web_id
        for account in self.accounts:
            if not hasattr(account, 'web_id'):
                account['web_id'] = self._generate_web_id()
        
        self._extract_web_id_from_cookie()
        
        # 如果没有从cookie中提取到web_id，则生成一个新的
        if not self.web_id:
            self.web_id = self._generate_web_id()
        
    def _extract_web_id_from_cookie(self):
        """从cookie中提取web_id"""
        try:
            account = self.get_current_account()
            if not account:
                return
                
            # 如果账号已有web_id，直接使用
            if account.get('web_id'):
                self.web_id = account['web_id']
                return
                
            # 否则生成新的web_id
            account['web_id'] = self._generate_web_id()
            self.web_id = account['web_id']
            
        except Exception as e:
            logger.error(f"[Dreamina] Failed to extract web_id from cookie: {e}")
            # 出错时生成新的web_id
            self.web_id = self._generate_web_id()
        
    def _generate_web_id(self):
        """生成新的web_id"""
        # 生成一个19位的随机数字字符串
        web_id = ''.join([str(random.randint(0, 9)) for _ in range(19)])
        return web_id
        
    def get_web_id(self):
        """获取web_id"""
        if not self.web_id:
            self.web_id = self._generate_web_id()
        return self.web_id
        
    def get_current_account(self):
        """获取当前账号"""
        if not self.accounts:
            return None
        return self.accounts[self.current_account_index]
        
    def switch_to_account(self, account_index):
        """切换到指定账号"""
        if not self.accounts:
            raise Exception("No accounts configured")
        if account_index < 0 or account_index >= len(self.accounts):
            logger.error(f"[Dreamina] Invalid account index: {account_index}, total accounts: {len(self.accounts)}")
            return None
        self.current_account_index = account_index
        logger.info(f"[Dreamina] Switched to account {account_index + 1}")
        return self.get_current_account()
        
    def get_account_count(self):
        """获取账号总数"""
        return len(self.accounts)

    def find_account_with_sufficient_credit(self, required_credit):
        """查找有足够积分的账号"""
        original_index = self.current_account_index
        
        # 检查所有账号
        for i in range(len(self.accounts)):
            credit_info = self.get_credit()
            if credit_info and credit_info["total_credit"] >= required_credit:
                logger.info(f"[Dreamina] Found account with sufficient credit: {credit_info['total_credit']}")
                return self.get_current_account()
            
            # 切换到下一个账号
            next_index = (self.current_account_index + 1) % len(self.accounts)
            self.switch_to_account(next_index)
        
        # 如果没有找到合适的账号，恢复原始账号
        self.switch_to_account(original_index)
        return None

    def get_token(self, api_path="/"):
        """获取token信息
        Args:
            api_path: API路径，用于生成不同的签名
        Returns:
            dict: token信息
        """
        try:
            account = self.get_current_account()
            if not account:
                logger.error("[Dreamina] ❌ 无法获取当前账号信息")
                return None
                
            # 获取当前时间戳
            timestamp = str(int(time.time()))
            
            # 生成新的msToken
            msToken = self._generate_ms_token()
            
            # 生成新的sign
            sign = self._generate_sign(api_path, timestamp)
            
            # 生成新的a_bogus
            a_bogus = self._generate_a_bogus(api_path, timestamp)
            
            # 生成新的cookie
            cookie = self._generate_cookie(account)
            

            
            return {
                "cookie": cookie,
                "msToken": msToken,
                "sign": sign,
                "a_bogus": a_bogus,
                "device_time": timestamp
            }
            
        except Exception as e:
            logger.error(f"[Dreamina] ❌ 生成Token失败: {str(e)}")
            return None
            
    def _generate_ms_token(self):
        """生成msToken"""
        # 生成107位随机字符串
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return ''.join(random.choice(chars) for _ in range(107))
        
    def _generate_sign(self, api_path, timestamp):
        """生成sign
        Args:
            api_path: API路径
            timestamp: 时间戳
        Returns:
            str: sign字符串
        """
        # 使用固定的key - 根据curl示例调整
        # curl示例: device-time: 1753430107, sign: f48b6d6e16d11500afae632895dbdb97
        # API路径: /artist/v2/tools/get_upload_token
        sign_str = f"9e2c|{api_path[-7:]}|{self.platform_code}|{self.version_code}|{timestamp}||11ac"
        logger.debug(f"[Dreamina] Sign生成: {sign_str}")
        return hashlib.md5(sign_str.encode()).hexdigest()
        
    def _generate_a_bogus(self, api_path, timestamp):
        """生成a_bogus
        Args:
            api_path: API路径
            timestamp: 时间戳
        Returns:
            str: a_bogus字符串
        """
        # 生成32位随机字符串
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return ''.join(random.choice(chars) for _ in range(32))
        
    def _generate_cookie(self, account):
        """生成完整的cookie
        Args:
            account: 账号信息
        Returns:
            str: 完整的cookie字符串
        """
        try:
            # 获取基本信息
            sessionid = account.get("sessionid", "")
            timestamp = int(time.time())
            
            # 生成过期时间（60天后）
            expire_time = timestamp + 60 * 24 * 60 * 60
            expire_date = time.strftime("%a, %d-%b-%Y %H:%M:%S GMT", time.gmtime(expire_time))
            
            # 使用账号的web_id或生成新的
            web_id = account.get('web_id', self._generate_web_id())
            if not account.get('web_id'):
                account['web_id'] = web_id
            
            # 构建cookie部分
            cookie_parts = [
                f"sessionid={sessionid}",
                f"sessionid_ss={sessionid}",
                f"_tea_web_id={web_id}",
                f"web_id={web_id}",
                f"_v2_spipe_web_id={web_id}",
                f"uid_tt={self.user_id}",
                f"uid_tt_ss={self.user_id}",
                f"sid_tt={sessionid}",
                f"sid_guard={sessionid}%7C{timestamp}%7C5184000%7C{expire_date}",
                f"ssid_ucp_v1=1.0.0-{hashlib.md5((sessionid + str(timestamp)).encode()).hexdigest()}",
                f"sid_ucp_v1=1.0.0-{hashlib.md5((sessionid + str(timestamp)).encode()).hexdigest()}",
                "store-region=cn-gd",
                "store-region-src=uid",
                "is_staff_user=false"
            ]
            
            return "; ".join(cookie_parts)
            
        except Exception as e:
            logger.error(f"[Dreamina] Error generating cookie: {str(e)}")
            return ""

    def get_credit(self):
        """获取积分信息 - 更新为最新API格式"""
        url = "https://commerce-api-sg.capcut.com/commerce/v1/benefits/user_credit"
        
        token_info = self.get_token("/commerce/v1/benefits/user_credit")
        if not token_info:
            logger.error("[Dreamina] 无法获取token信息")
            return self._get_fallback_credit()
            
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'cookie': token_info["cookie"],
            'Origin': 'https://dreamina.capcut.com',
            'Referer': 'https://dreamina.capcut.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'appid': '513641',
            'appvr': '5.8.0',
            'device-time': token_info["device_time"],
            'lan': 'EN',
            'pf': '7',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Microsoft Edge";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sign': token_info["sign"],
            'sign-ver': '1'
        }
        
        try:
            logger.info("[Dreamina] 🔍 正在获取积分信息...")
            response = requests.post(url, headers=headers, json={}, timeout=30)
            
            # 检查响应状态码
            if response.status_code != 200:
                logger.error(f"[Dreamina] ❌ 积分查询失败，HTTP状态码: {response.status_code}")
                return self._get_fallback_credit()
            
            # 检查响应内容是否为空
            if not response.text:
                logger.error("[Dreamina] ❌ 积分查询失败，响应内容为空")
                return self._get_fallback_credit()
            
            # 尝试解析JSON
            try:
                result = response.json()
                # 简化日志 - 只显示成功状态，不显示完整JSON
                logger.debug(f"[Dreamina] 📊 积分API响应成功")
            except json.JSONDecodeError as e:
                logger.error(f"[Dreamina] 解析积分信息JSON失败: {e}")
                return self._get_fallback_credit()
            
            # 解析新的API响应格式
            if result.get("ret") == "0":
                # 解析response字段中的JSON数据
                response_str = result.get("response", "{}")
                try:
                    credit_data = json.loads(response_str)
                except json.JSONDecodeError:
                    # 备用方案：从data字段获取
                    credit_data = result.get("data", {})
                    
                if credit_data:
                    credit_info = credit_data.get("credit", {})
                    gift_credit = credit_info.get("gift_credit", 0)
                    purchase_credit = credit_info.get("purchase_credit", 0)
                    vip_credit = credit_info.get("vip_credit", 0)
                    total_credit = gift_credit + purchase_credit + vip_credit
                    
                    logger.info(f"[Dreamina] ✅ 积分信息获取成功 - 账号{self.current_account_index + 1}:")
                    logger.debug(f"[Dreamina]   - 赠送积分: {gift_credit}")
                    logger.debug(f"[Dreamina]   - 购买积分: {purchase_credit}")
                    logger.debug(f"[Dreamina]   - VIP积分: {vip_credit}")
                    logger.debug(f"[Dreamina]   - 总积分: {total_credit}")
                    
                    # 检查过期积分信息
                    expiring_credits = credit_data.get("expiring_credits", [])
                    if expiring_credits:
                        for expiring in expiring_credits:
                            expire_time = expiring.get("expire_time", 0)
                            expire_amount = expiring.get("credit_amount", 0)
                            if expire_time > 0:
                                expire_date = datetime.datetime.fromtimestamp(expire_time).strftime('%Y-%m-%d %H:%M:%S')
                                logger.debug(f"[Dreamina]   - 即将过期: {expire_amount}积分，过期时间: {expire_date}")
                    
                    return {
                        "gift_credit": gift_credit,
                        "purchase_credit": purchase_credit,
                        "vip_credit": vip_credit,
                        "total_credit": total_credit,
                        "is_free_period": False,
                        "expiring_credits": expiring_credits,
                        "credits_detail": credit_data.get("credits_detail", {})
                    }
                else:
                    logger.warning("[Dreamina] 积分信息数据为空")
                    return self._get_fallback_credit()
            else:
                error_msg = result.get("errmsg", "未知错误")
                logger.error(f"[Dreamina] 积分获取失败: {error_msg}")
                return self._get_fallback_credit()
                
        except requests.exceptions.Timeout:
            logger.error("[Dreamina] 获取积分信息超时")
            return self._get_fallback_credit()
        except requests.exceptions.ConnectionError:
            logger.error("[Dreamina] 网络连接错误")
            return self._get_fallback_credit()
        except Exception as e:
            logger.error(f"[Dreamina] 获取积分信息时发生异常: {str(e)}")
            return self._get_fallback_credit()
    
    def _get_fallback_credit(self):
        """获取积分失败时的备用返回值"""
        logger.info("[Dreamina] 💡 使用备用积分信息（当前可能处于限免阶段）")
        return {
            "gift_credit": 999999,
            "purchase_credit": 0,
            "vip_credit": 0,
            "total_credit": 999999,
            "is_free_period": True,
            "expiring_credits": [],
            "credits_detail": {}
        }
        
    def get_credit_history(self, count=20, cursor="0"):
        """获取积分历史记录 - 新增功能"""
        url = "https://commerce-api-sg.capcut.com/commerce/v1/benefits/user_credit_history"
        
        token_info = self.get_token("/commerce/v1/benefits/user_credit_history")
        if not token_info:
            logger.error("[Dreamina] 无法获取token信息")
            return None
            
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'cookie': token_info["cookie"],
            'Origin': 'https://dreamina.capcut.com',
            'Referer': 'https://dreamina.capcut.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'appid': '513641',
            'appvr': '5.8.0',
            'device-time': token_info["device_time"],
            'lan': 'EN',
            'pf': '7',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Microsoft Edge";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sign': token_info["sign"],
            'sign-ver': '1'
        }
        
        data = {
            "count": count,
            "cursor": cursor
        }
        
        try:
            logger.info(f"[Dreamina] 🔍 正在获取积分历史记录（数量：{count}，游标：{cursor}）...")
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            logger.info(f"[Dreamina] 📡 积分历史API响应状态: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"[Dreamina] 获取积分历史失败，HTTP状态码: {response.status_code}")
                logger.error(f"[Dreamina] 响应内容: {response.text[:200]}...")
                return None
            
            if not response.text:
                logger.error("[Dreamina] 获取积分历史失败，响应内容为空")
                return None
            
            try:
                result = response.json()
                logger.info(f"[Dreamina] 📊 积分历史API原始响应结构: ret={result.get('ret')}, 数据字段={list(result.keys())}")
            except json.JSONDecodeError as e:
                logger.error(f"[Dreamina] 解析积分历史JSON失败: {e}")
                logger.error(f"[Dreamina] 原始响应: {response.text[:300]}...")
                return None
            
            if result.get("ret") == "0":
                # 新API格式：数据可能在data字段或response字段（JSON字符串）
                history_data = None
                
                # 方案1：尝试从data字段获取数据
                if result.get("data"):
                    history_data = result.get("data")
                    logger.info("[Dreamina] 📦 从data字段获取积分历史数据")
                
                # 方案2：如果data字段为空或不存在，尝试解析response字段
                if not history_data and result.get("response"):
                    try:
                        response_str = result.get("response")
                        if isinstance(response_str, str):
                            history_data = json.loads(response_str)
                            logger.info("[Dreamina] 📦 从response字段解析积分历史数据")
                        else:
                            history_data = response_str
                            logger.info("[Dreamina] 📦 response字段已经是对象格式")
                    except json.JSONDecodeError as e:
                        logger.error(f"[Dreamina] 解析response字段JSON失败: {e}")
                        return None
                
                if history_data:
                    records = history_data.get("records", [])
                    new_cursor = history_data.get("new_cursor", "0")
                    has_more = history_data.get("has_more", False)
                    total_credit = history_data.get("total_credit", 0)
                    
                    logger.info(f"[Dreamina] ✅ 积分历史获取成功:")
                    logger.info(f"[Dreamina]   - 当前总积分: {total_credit}")
                    logger.info(f"[Dreamina]   - 历史记录数: {len(records)}")
                    logger.info(f"[Dreamina]   - 是否还有更多: {has_more}")
                    logger.info(f"[Dreamina]   - 下一页游标: {new_cursor}")
                    
                    # 记录详细的历史记录
                    for i, record in enumerate(records[:5]):  # 只显示前5条
                        try:
                            create_time = record.get("create_time", 0)
                            if create_time > 0:
                                create_date = datetime.datetime.fromtimestamp(create_time).strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                create_date = "未知时间"
                            
                            amount = record.get("amount", 0)
                            title = record.get("title", "未知操作")
                            history_type = record.get("history_type", 0)
                            status = record.get("status", "未知状态")
                            
                            logger.info(f"[Dreamina]   记录{i+1}: {create_date} | {title} | {amount}积分 | 类型{history_type} | {status}")
                        except Exception as e:
                            logger.warning(f"[Dreamina] 解析历史记录{i+1}时出错: {e}")
                    
                    return {
                        "records": records,
                        "new_cursor": new_cursor,
                        "has_more": has_more,
                        "total_credit": total_credit
                    }
                else:
                    logger.warning("[Dreamina] 积分历史数据为空（data和response字段都为空）")
                    return None
            else:
                error_msg = result.get("errmsg", "未知错误")
                logger.error(f"[Dreamina] 积分历史获取失败: ret={result.get('ret')}, errmsg={error_msg}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("[Dreamina] 获取积分历史超时")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("[Dreamina] 获取积分历史时网络连接错误")
            return None
        except Exception as e:
            logger.error(f"[Dreamina] 获取积分历史时发生异常: {str(e)}")
            import traceback
            logger.error(f"[Dreamina] 详细异常信息: {traceback.format_exc()}")
            return None
            
    def receive_daily_credit(self):
        """领取每日积分"""
        url = "https://mweb-api-sg.capcut.com/commerce/v1/benefits/credit_receive"
        
        params = {
            "aid": "513695",
            "device_platform": "web",
            "region": "HK"
        }
        
        token_info = self.get_token("/commerce/v1/benefits/credit_receive")
        if not token_info:
            return None
            
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'app-sdk-version': self.version_code,
            'appid': '513695',
            'appvr': self.version_code,
            'content-type': 'application/json',
            'cookie': token_info["cookie"],
            'device-time': token_info["device_time"],
            'sign': token_info["sign"],
            'sign-ver': '1',
            'pf': self.platform_code,
            'priority': 'u=1, i',
            'referer': 'https://mweb-api-sg.capcut.com/ai-tool/image/generate',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'msToken': token_info["msToken"],
            'x-bogus': token_info["a_bogus"]
        }
        
        try:
            response = requests.post(url, headers=headers, params=params, json={"time_zone": "Asia/Shanghai"})
            result = response.json()
            
            if result.get("ret") == "0" and result.get("data"):
                data = result["data"]
                logger.info(f"[Dreamina] Account {self.current_account_index + 1} received daily credit: {data['receive_quota']}, total credit: {data['cur_total_credits']}")
                return data['cur_total_credits']
            else:
                logger.error(f"[Dreamina] Failed to receive daily credit: {result}")
                return None
                
        except Exception as e:
            logger.error(f"[Dreamina] Error in receive_daily_credit: {str(e)}")
            return None

    def get_upload_token(self):
        """获取上传token"""
        url = "https://mweb-api-sg.capcut.com/mweb/v1/get_upload_token"
        
        params = {
            "aid": "513695",
            "device_platform": "web",
            "region": "HK"
        }
        
        # 获取最新的token信息
        token_info = self.get_token("/mweb/v1/get_upload_token")
        if not token_info:
            return None
            
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'app-sdk-version': '48.0.0',
            'appid': '513695',
            'appvr': '5.8.0',
            'content-type': 'application/json',
            'cookie': token_info["cookie"],
            'device-time': token_info["device_time"],
            'lan': 'en',
            'loc': 'HK',
            'origin': 'https://mweb-api-sg.capcut.com',
            'pf': '7',
            'priority': 'u=1, i',
            'referer': 'https://mweb-api-sg.capcut.com/ai-tool/video/generate',
            'sign': token_info["sign"],
            'sign-ver': '1',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'msToken': token_info["msToken"],
            'x-bogus': token_info["a_bogus"]
        }
        
        data = {
            "scene": 2
        }
        
        try:
            response = requests.post(url, headers=headers, params=params, json=data)
            result = response.json()
            
            if result.get("ret") == "0" and result.get("data"):
                token_data = result["data"]
                return {
                    "access_key_id": token_data["access_key_id"],
                    "secret_access_key": token_data["secret_access_key"],
                    "session_token": token_data["session_token"],
                    "space_name": token_data["space_name"],
                    "upload_domain": token_data["upload_domain"]
                }
            else:
                logger.error(f"[Dreamina] Failed to get upload token: {result}")
                return None
                
        except Exception as e:
            logger.error(f"[Dreamina] Error in get_upload_token: {str(e)}")
            return None