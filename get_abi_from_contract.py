'''
SUI DOC: https://docs.sui.io/concepts/sui-move-concepts
RPC API: https://docs.shinami.com/reference/sui-api

Node Host:
- https://api.shinami.com/node/v1/<APIKEY>
- https://fullnode.mainnet.sui.io

APIs:
- sui_getLatestCheckpointSequenceNumber
- sui_getCheckpoint / sui_getCheckpoints
- sui_multiGetTransactionBlocks
'''

import requests
import json
import logging
import time
import os
import re

type_mapping = {
    "U8": "uint8",
    "U16": "uint16",
    "U32": "uint32",
    "U64": "uint64",
    "U128": "uint128",
    "U256": "uint256",
    "<struct<String>>": "String",
    "<struct<String>>": "String",
    "<struct<ID>>": "Address",
    "Bool" : "bool"
}

# 创建正则表达式模式，| 表示或，用于匹配字典中的任意键
pattern = re.compile("|".join(map(re.escape, type_mapping.keys())))

TxContext = {'MutableReference': {'Struct': {'address': '0x2', 'module': 'tx_context', 'name': 'TxContext', 'typeArguments': []}}}

# 替换函数
def replace(match):
    return type_mapping[match.group(0)]

logging.basicConfig(level='INFO', format='%(asctime)s %(levelname)s %(message)s')

SUI_NODE_HOSTS = [
    'https://fullnode.mainnet.sui.io',
]
SUI_NODE_HOST = SUI_NODE_HOSTS[-1]


def safe_requesets(method, url: str, payload=None, headers=None, retries=1, timeout=(10, 30)):
    if not url.startswith(('https', 'http')):
        url = "https://{}".format(url.lstrip(':/'))

    if not headers or not isinstance(headers, dict):
        headers = {}
    headers["user-Agent"] = 'Mozilla/5.0 (Macintosh; Intel Mac OS x 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
    if method == 'POST':
        headers['Content-Type'] = 'application/json'

    for _retries in range(1, retries + 1):
        try:
            resp = None
            if method == 'GET':
                resp = requests.get(url, headers=headers, data=json.dumps(payload) if payload else None, timeout=timeout)
            elif method == 'POST' and payload:
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            # logging.info("request to {} used {} seconds".format(url, resp.elapsed.total_seconds()))
            if resp and resp.status_code == 200:
                return resp
            # logging.info(f'invalid response {method} on {url}, msg: {resp.text if resp is not None else None}')
        except Exception as e:
            logging.error(f"exception on {method} on {url}, msg: {str(e)}, retry:{_retries}")

        if _retries < retries:
            tm_sleep = 2 ** _retries
            logging.info(f'retry {_retries}/{retries} in {tm_sleep} second(s)')
            time.sleep(tm_sleep)
    return None


def sui_rpc_cmd(cmd, params, default_value={}):
    try:
        data = {
            "jsonrpc": '2.0',
            'method': cmd,
            "params": params,
            "id": 1
        }
        r = safe_requesets('POST', SUI_NODE_HOST, data)
        if r:
            return r.json().get('result', default_value)
    except Exception as e:
        logging.exception(e)

    return default_value


def sui_rpc_cmds(cmd, params, default_value={}):
    try:
        data = [{
            "jsonrpc": '2.0',
            'method': cmd,
            "params": p,
            "id": i
        } for i, p in enumerate(params, 1)]

        r = safe_requesets('POST', SUI_NODE_HOST, data)
        if r:
            return r.json()
    except Exception as e:
        logging.exception(e)

    return default_value

##################################################################


def dicts_to_json(dicts,data_file):
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r') as file:
                try:
                    data = json.load(file)
                except json.JSONDecodeError:
                    data = []
        except IOError as e:
            logging.error(f"Error reading file {data_file}: {e}")
            data = []
    else:
        data = []

    data.append(dicts)
    try:
        with open(data_file, 'w') as file:
            json.dump(data, file)
    except IOError as e:
        logging.error(f"Error writing file {data_file}: {e}")


def is_event(dicts):
    event_abilities = dicts.get("abilities", {}).get("abilities", [])
    return 'Copy' in event_abilities and 'Drop' in event_abilities and 'Key' not in event_abilities


def format_type_arguments(type_args, level=0):
    """
    Formats type arguments into a string representation, handling nested Structs.
    """
    if not type_args:
        return ""

    formatted_args = []
    if isinstance(type_args, dict):
        struct_data = type_args.get("Struct", {})
        if struct_data:
            struct_name = struct_data.get("name", "")
            # struct_address = struct_data.get("address", "")
            # struct_module = struct_data.get("module", "")
            nested_type_args = struct_data.get("typeArguments", [])
            if nested_type_args:
                formatted_args.append(f"struct<{struct_name}<{format_type_arguments(nested_type_args, level + 1)}>>")
            else:
                formatted_args.append(f"struct<{struct_name}>")
        else:
            type_parameter = type_args.get("TypeParameter")
            if type_parameter:
                formatted_args.append(f"T{type_parameter}")
            elif "Vector" in type_args:
                vector_data = type_args.get("Vector", {})
                formatted_args.append(f"vector<{format_type_arguments(vector_data, level + 1)}>")
            elif "TypeParameter" in type_args:
                TypeParameter_data = type_args.get("TypeParameter","")
                formatted_args.append(f"T{TypeParameter_data}")
            else:    
                # Handling other nested types
                formatted_args.append(f"UnknownType")
    elif isinstance(type_args, list):
        for arg in type_args:
            if isinstance(arg,dict):
                formatted_args.append(format_type_arguments(arg,level +1))
            else:    
                formatted_args.append(arg)
    else:
        formatted_args.append(type_args)

    return f"{','.join(formatted_args)}" if formatted_args else ""

def create_dict(parameters_dicts, field, k):
    field_data = parameters_dicts.get(field, {})

    if isinstance(field_data, dict):
        # parameters_dict = {"name": f"Arg{k}"}
        if field == "MutableReference":
            parameters_dict = pattern.sub(replace,f"&mut<{format_type_arguments(field_data)}>")
        elif field == "Reference":
            parameters_dict = pattern.sub(replace,f"&<{format_type_arguments(field_data)}>")
        elif field == "Vector":
            parameters_dict = pattern.sub(replace,f"Vector<{format_type_arguments(field_data)}>")
        elif field == "Struct":
            parameters_dict = {"name": f"Arg{k}"}
            parameters_dict = pattern.sub(replace,f"<{format_type_arguments(parameters_dicts)}>")
        else:
            logging.warning(f"Unhandled field type: {field}")

        return parameters_dict

    elif isinstance(field_data, str):
        if field == "Vector":
            return pattern.sub(replace,f"vector<{format_type_arguments(parameters_dicts)}>")
        else:    
            return pattern.sub(replace,format_type_arguments(field_data))
    else:
        logging.warning(f"Unexpected field data type: {type(field_data)}")
        return None
    
    
def change_func_inputs_abi(data):
    data_list = []

    # 处理 typeParameters 数据
    typeParameters_data = data.get("typeParameters", [])
    if typeParameters_data:
        data_list.extend({
            "name": f"T{idt}",
            "type": f"Type{idt}"
        } for idt in range(len(typeParameters_data)))
    else:
        logging.info("typeParameters_data is null")

    # 处理 parameters 数据
    parameters_data = data.get("parameters", [])
    if parameters_data:
        for parameters_id, parameters_value in enumerate(parameters_data):
            if isinstance(parameters_value, str):
                data_list.append({
                    "name": f"Arg{parameters_id}",
                    "type": pattern.sub(replace,parameters_value)
                })
            elif isinstance(parameters_value, dict):
                if parameters_value == TxContext:
                    continue
                for field in parameters_value.keys():
                    result = create_dict(parameters_value, field, parameters_id)
                    if result:
                        data_list.append({
                            "name": f"Arg{parameters_id}",
                            "type": pattern.sub(replace,result)
                            })
            else:
                logging.error(f"Error: Unexpected type for parameter at index {parameters_id}")
    else:
        logging.info("parameters_data is null")
        

    return data_list


def change_func_outputs_abi(data):
    return_list = []

    # 获取 "return" 数据，确保数据存在且为列表
    return_data = data.get("return", [])
    if not return_data:
        logging.info('no outputs')
        return return_list
    
    for return_id, return_value in enumerate(return_data):
        if isinstance(return_value,str):
            return_list.append({
                "name": f"result{return_id}",
                "type": f"{pattern.sub(replace,return_value)}"
            })
        else:
            for value in return_value:
                result = create_dict(return_value, value, return_id)
                if result:
                    return_list.append({
                        "name" : f"result{return_id}",
                        "type" : f"{pattern.sub(replace,result)}"
                    })
                else:
                    logging.error("no data return")    

    return return_list     

def change_event_abi(dicts):
    event_data = []

    fields_data = dicts.get("fields", [])
    if fields_data:
        for fields_value in fields_data:
            event_type = fields_value.get("type", {})
            field_dict = {"name": fields_value.get("name", {})}

            if isinstance(event_type, str):
                field_dict["type"] = pattern.sub(replace,event_type)
            elif isinstance(event_type, dict):
                for type_data, type_value in event_type.items():
                    if type_data == "Vector":
                        field_dict["type"] = pattern.sub(replace,f"vector<{format_type_arguments(type_value)}>")
                    elif type_data == "Struct":
                        field_dict["type"] = pattern.sub(replace,f"<{format_type_arguments(event_type)}>")
                    elif type_data == "TypeParameter":
                        field_dict["type"] = pattern.sub(replace,f"T{type_value}")
                    else:
                        logging.warning("There is no such type available",type_data)
            event_data.append(field_dict)
    else:
        logging.info("fields_data is null")

    return event_data


def get_abi_from_contract(contract_address):
    """
    获取合约的事件和函数 ABI 并存储到 JSON 文件中
    """
    # 获取合约的规范化模块
    res = sui_rpc_cmd('sui_getNormalizedMoveModulesByPackage', [contract_address])

    file_name = f"./test/{contract_address[:6]}_abi.json"
    
    if not isinstance(res, dict):
        logging.error("Invalid response from RPC call")
        return
    
    found_event = False
    found_function = False
    
    for module_key, module_dict in res.items():
        # 处理事件 ABI
        event_dicts = module_dict.get("structs", {})
        for event_name, event_dict in event_dicts.items():
            if is_event(event_dict):
                event_data = []
                typeParameters_data = event_dict.get("typeParameters", [])
                if typeParameters_data:
                    for idt in range(len(typeParameters_data)):
                        event_data.append(f"Ty{idt}")
                        inlay_data = f"{','.join(event_data)}" if event_data else ""
                    name = f'{module_key}::{event_name}<{inlay_data}>'
                else:
                    name = f'{module_key}::{event_name}'
                event_abi_dict = {
                    "name": name,
                    "type": "event",
                    "inputs": change_event_abi(event_dict)
                }
                
                dicts_to_json(event_abi_dict, file_name)
                logging.info(f"Event ABI stored in {file_name}")
                found_event = True

        # 处理函数 ABI
        function_dicts = module_dict.get("exposedFunctions", {})
        function_isEntry_dicts = {f"{module_key}::{func_name}": func_dict 
                                  for func_name, func_dict in function_dicts.items() 
                                #   if func_dict.get("isEntry")
                                  }
        
        for name, function_dict in function_isEntry_dicts.items():
            function_abi_dict = {
                "name": name,
                "type": "function",
                "inputs": change_func_inputs_abi(function_dict),
                "outputs": change_func_outputs_abi(function_dict)
            }
            
            dicts_to_json(function_abi_dict, file_name)
            logging.info(f"Function ABI stored in {file_name}")
            found_function = True

    if not found_event:
        logging.info(f"No events found in contract {contract_address[:6]}")
    if not found_function:
        logging.info(f"No functions found in contract {contract_address[:6]}")

def get_function_abi(contract_address):
    # 获取合约的规范化模块
    res = sui_rpc_cmd('sui_getNormalizedMoveModulesByPackage', [contract_address])
    function_isEntry_dicts = {}

    # 检查返回结果的有效性
    if not isinstance(res, dict):
        logging.error("Invalid response from RPC call")
        return

    # 遍历返回的模块
    for module_key in res:
        module_dict = res.get(module_key, {})
        function_dicts = module_dict.get("exposedFunctions", {})

        # 提取入口函数
        for func_name, func_dict in function_dicts.items():
            if func_dict.get("isEntry"):
                function_isEntry_dicts[f"{module_key}::{func_name}"] = func_dict

    # 处理每个入口函数
    for name, function_dict in function_isEntry_dicts.items():
        logging.info(f"Processing function: {name}")

        import pdb
        
        function_abi_dict = {
            "name": name,
            "type": "function",
            "inputs": change_func_inputs_abi(function_dict),
            "outputs": change_func_outputs_abi(function_dict)
        }

        # 将 ABI 信息写入 JSON 文件
        file_name = f"{contract_address[:6]}_func.json"
        dicts_to_json(function_abi_dict, file_name)

        logging.info(file_name)


def get_event_abi(contract_address):
    """
    获取合约的事件 ABI 并存储到 JSON 文件中
    """
    # 获取合约的规范化模块
    res = sui_rpc_cmd('sui_getNormalizedMoveModulesByPackage', [contract_address])
    
    if not isinstance(res, dict):
        logging.error("Invalid response from RPC call")
        return

    for module_key, module_dict in res.items():
        event_dicts = module_dict.get("structs", {})

        for event_name, event_dict in event_dicts.items():
            logging.info(f"Processing event: {event_name}")
            if is_event(event_dict):
                event_abi_dict = {
                    "name": f'{contract_address}::{module_key}::{event_name}',
                    "type": "event",
                    "inputs": change_event_abi(event_dict)
                }
                
                file_name = f"{contract_address[:6]}_event.json"
                dicts_to_json(event_abi_dict, file_name)
            else:
                logging.info(f"No events found in contract {contract_address[:6]}")

if __name__ == '__main__':
    package_ids = [
        # "0x000000000000000000000000000000000000000000000000000000000000dee9",
        # "0x3e8e806c3028adfffec57e380bb458f8286b73f1bf9b8906f89a2bb6b817616c",
        # "0x640d44dbdc0ede165c7cc417d7f57f1b09648083109de7132c6b3fb15861f5ee",
        # "0x5306f64e312b581766351c07af79c72fcb1cd25147157fdc2f8ad76de9a3fb6a",
        # "0x785248249ac457dfd378bdc6d2fbbfec9d1daf65e9d728b820eb4888c8da2c10",
        # "0xb58b33843a07c2a7cf2707ca3ebf00d6de2ae1e5a273172c3615e9fd76d7e186",
        # "0xd92bc457b42d48924087ea3f22d35fd2fe9afdf5bdfe38cc51c0f14f3282f6d5",
        # "0xdeeb7a4662eec9f2f3def03fb937a663dddaa2e215b8078a284d026b7946c270"
        # "0x1a3c42ded7b75cdf4ebc7c7b7da9d1e1db49f16fcdca934fac003f35f39ecad9"
        # "0xcec352932edc6663a118e8d64ed54da6b8107e8719603bf728f80717592cd9e8"
        # "0x1eabed72c53feb3805120a081dc15963c204dc8d091542592abaf7a35689b2fb"
        "0x2"
        
        
        ]
    for package_id in package_ids:
        get_abi_from_contract(package_id)
