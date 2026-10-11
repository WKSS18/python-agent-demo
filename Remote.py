# Version1.3
import requests
import json
import os
import yaml
import socket


def remote(method, *args, **kwargs):
    """
    执行远程服务方法
    :param method: 方法名称
    :param args:
    :param kwargs:
    :return:
    """
    res_json = None
    try:
        hostname = socket.gethostname().encode("utf-8")
        url = "http://test-arch-auto-core.dasouche-inc.net/libExecutorController/executeLibMethod.json"
        test_core_env = None
        try:
            test_core_env = get_settings("excute_env")
        except:
            pass
        if test_core_env:
            if test_core_env == "prepub" or test_core_env == "prod":
                test_core_env = "prepub"
            else:
                test_core_env = "stable"
        else:
            test_core_env = "stable"
        headers = {
            "Content-Type": "application/json",
            "method_executor": hostname,
            "test-core-env": test_core_env
        }
        if method == "database query" or method == "database update":
            kwargs["asDict"] = True
        data_json = {
            "method": method,
            "args": args,
            "kwargs": kwargs
        }
        res = requests.request(method="POST", url=url, headers=headers, json=data_json)
        res_json = json.loads(res.text)
    except Exception as e:
        raise Exception("remote远程调用方法报错")
    if res_json:
        if res_json["code"] == "200":
            print("远程关键字{0}执行日志如下：\n{1}".format(method, res_json["data"]["log"]))
            return res_json["data"]["data"]
        else:
            print(res_json["msg"])
            raise Exception(res_json["msg"])


def get_settings(*args):
    """
    获取guardian配置文件的配置对象
    :return:
    """
    try:
        from attrdict import AttrDict
    except:
        os.system("pip install attrdict")
        from attrdict import AttrDict
    project_dir = os.path.dirname(__file__)
    # 获取运行环境
    with open('{0}/config/settings.yaml'.format(project_dir)) as fileobject:
        setting_default = AttrDict(yaml.safe_load(fileobject))
        env = setting_default["excute_env"]
    with open('{0}/config/settings_{1}.yaml'.format(project_dir, env)) as fileobject:
        setting = AttrDict(yaml.safe_load(fileobject))
    try:
        for arg in args:
            setting = setting[arg]
        return setting
    except Exception as e:
        for arg in args:
            setting_default = setting_default[arg]
        return setting_default


if __name__ == '__main__':
    pass