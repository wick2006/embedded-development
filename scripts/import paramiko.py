import paramiko
from scp import SCPClient
import os
import glob
import time
import sys
import serial

# ================= 基础配置 =================
# 设备默认IP 
DEVICE_IP = '192.168.1.2' 
SSH_PORT = 22
USERNAME = 'root'
PASSWORD = 'root' 
# 远程临时目录 (/dev/shm)
REMOTE_TEMP = '/dev/shm' 

# 串口配置
SERIAL_PORT = 'COM3'
BAUDRATE = 115200

# ================= 路径配置 =================
# 获取当前脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 获取上一级目录
PARENT_DIR = os.path.dirname(BASE_DIR)

# 1. USB音频补丁目录
# ss528v100增加USB音频
AUDIO_PATCH_DIR_NAME = 'ss528v100增加USB音频'
LOCAL_AUDIO_PATH = os.path.join(PARENT_DIR, AUDIO_PATCH_DIR_NAME)

# 2. 应用安装包
# 将通过 find_app_package() 动态查找
# ======================================================

def create_ssh_client():
    """创建 SSH 连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print(f" 正在连接设备 {DEVICE_IP}...")
        client.connect(DEVICE_IP, port=SSH_PORT, username=USERNAME, password=PASSWORD, timeout=10)
        return client
    except Exception as e:
        print(f" 连接失败: {e}")
        return None

def exec_cmd(ssh, command, ignore_error=False):
    """执行 SSH 命令并检查结果"""
    # print(f"   [CMD] {command}") 
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    
    output = stdout.read().decode().strip()
    error = stderr.read().decode().strip()
    
    if exit_status != 0 and not ignore_error:
        print(f" 命令执行失败: {command}")
        print(f" 错误信息: {error}")
        return False
    return True

def find_app_package():
    """
    在上一级目录自动搜寻应用安装包
    规则: install_dt-*-ss528v100-Linux.tar.gz 
    """
    pattern = os.path.join(PARENT_DIR, 'install_dt-*-ss528v100-Linux.tar.gz')
    files = glob.glob(pattern)
    
    if not files:
        print(f" 未在目录 {PARENT_DIR} 中找到应用安装包！")
        print("   请确保文件命名格式为: install_dt-XX.YY.ZZ.NNNN-ss528v100-Linux.tar.gz")
        sys.exit(1)
    
    # 如果有多个，取修改时间最新的
    latest_file = max(files, key=os.path.getmtime)
    print(f"✅ 发现应用包: {os.path.basename(latest_file)}")
    return latest_file

def step_1_usb_audio(ssh):
    """
    步骤 4.2.2: ss528v100增加USB音频 
    """
    print("\n[1/3] 安装 USB 音频补丁...")
    
    if not os.path.exists(LOCAL_AUDIO_PATH):
        print(f"本地补丁目录不存在: {LOCAL_AUDIO_PATH}")
        return False

    print("   正在上传补丁文件...")
    # 使用 SCP 遍历上传目录下的所有文件
    with SCPClient(ssh.get_transport()) as scp:
        for filename in os.listdir(LOCAL_AUDIO_PATH):
            full_path = os.path.join(LOCAL_AUDIO_PATH, filename)
            if os.path.isfile(full_path):
                scp.put(full_path, remote_path=REMOTE_TEMP)

    # 执行文档中的命令序列
    commands = [
        # 更新内核
        f"cd {REMOTE_TEMP} && chmod +x ./fip.bin.sh",
        f"cd {REMOTE_TEMP} && ./fip.bin.sh",
        
        # 拷贝工具
        "mount -o remount,rw /", # 重新挂载根目录为可写
        f"cd {REMOTE_TEMP} && tar -xzvf alsa-lib_utils.tar.gz",
        f"cd {REMOTE_TEMP} && cp -f alsa-utils-1.2.9/bin/* /usr/bin/",
        
        # 拷贝配置文件
        "mkdir -p /root/hi626/lib-36a/_install/",
        f"cd {REMOTE_TEMP} && cp -rf alsa-lib-1.2.9/ /root/hi626/lib-36a/_install/",
        
        # 增加用户组
        "addgroup audio"
    ]
    
    for cmd in commands:
        if not exec_cmd(ssh, cmd):
            return False
            
    print("   USB 音频补丁安装成功")
    return True

def step_2_install_app(ssh):
    """
    步骤 4.2.3: 应用安装
    """
    local_pkg = find_app_package()
    pkg_name = os.path.basename(local_pkg)
    print(f"\n[2/3] 安装应用: {pkg_name} ")
    
    print("   正在上传应用包...")
    with SCPClient(ssh.get_transport()) as scp:
        scp.put(local_pkg, os.path.join(REMOTE_TEMP, pkg_name))
        
    # 处理解压后的目录名 (去除 .tar.gz)
    if pkg_name.endswith('.tar.gz'):
        dir_name = pkg_name[:-7]
    else:
        dir_name = pkg_name

    commands = [
        f"cd {REMOTE_TEMP} && tar -xzvf {pkg_name}", # 解压
        f"cd {REMOTE_TEMP}/{dir_name} && chmod +x ./install.sh",
        f"cd {REMOTE_TEMP}/{dir_name} && ./install.sh" # 执行安装脚本
    ]
    
    for cmd in commands:
        if not exec_cmd(ssh, cmd):
            return False

    print("  应用安装脚本执行完毕")
    return True

def step_3_boot_logo(ssh):
    """
    步骤 4.2.5: 开机画面设置 (Linux)
    """
    print("\n设置开机画面...")
    
    # 源文件在设备上的 /app/dt/cfg/
    commands = [
        "cp /app/dt/cfg/bootlogo-hg.jpg /recovery/bootlogo.jpg",
        "dd if=/recovery/bootlogo.jpg of=/dev/mmcblk0p4 bs=1024"
    ]
    
    for cmd in commands:
        if not exec_cmd(ssh, cmd):
            return False
            
    print("开机画面设置成功 (请注意还需要在Uboot设置参数)")
    return True

def wait_for_device_online(timeout=300):
    """等待设备上线 (用于烧录完后自动衔接)"""
    print(" 等待设备上线 (Ping)...")
    start = time.time()
    while time.time() - start < timeout:
        response = os.system(f"ping -n 1 -w 1000 {DEVICE_IP} > nul")
        if response == 0:
            print("设备已上线")
            time.sleep(5) # 等待 SSH 服务启动
            return True
        time.sleep(2)
    print("等待超时，设备未上线")
    return False

def step_4_uboot_settings(serial_port):
    """通过串口修改 U-Boot 环境变量"""
    print(f"\n[4/4] 正在连接串口 {serial_port} 以修改 U-Boot 参数...")
    
    try:
        ser = serial.Serial(serial_port, BAUDRATE, timeout=0.1)
        print("  串口已打开，正在等待设备重启...")
        
        start_time = time.time()
        interrupted = False
        
        # 拦截阶段
        while time.time() - start_time < 60: 
            ser.write(b'\n') 
            if ser.in_waiting:
                try:
                    output = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    if "hisilicon #" in output or "=>" in output or "Running U-Boot" in output:
                        ser.write(b'\n')
                        time.sleep(0.5)
                        ser.read_all()
                        interrupted = True
                        print("\n进入 U-Boot")
                        break
                except:
                    pass
            time.sleep(0.1)
            
        if not interrupted:
            print("超时未检测到 U-Boot 提示符。请检查串口连接。")
            ser.close()
            return False

        # 下发命令
        cmds = [
            'setenv bootcmd "setvobg 0 0; run run_logo; run update_script;"',
            'saveenv',
            'reset'
        ]
        
        for cmd in cmds:
            print(f"  发送 U-Boot 命令: {cmd}")
            ser.write((cmd + "\n").encode('utf-8'))
            time.sleep(1) 
            if ser.in_waiting:
                print(f"  [回显] {ser.read(ser.in_waiting).decode('utf-8', errors='ignore').strip()}")
        
        print("U-Boot 修改完成，设备重启")
        ser.close()
        return True

    except serial.SerialException as e:
        print(f"串口错误: {e}")
        return False
    except Exception as e:
        print(f"未知错误: {e}")
        return False
    
# ================= 主程序 =================
if __name__ == "__main__":
    print(f"当前工作基准: {BASE_DIR}")
    print(f"上一级资源目录: {PARENT_DIR}")
    
    # 1. 等待设备上线
    if not wait_for_device_online():
        sys.exit(1)

    # 2. 建立 SSH 连接
    ssh = create_ssh_client()
    if not ssh:
        sys.exit(1)

    try:
        # 3. 按顺序执行部署步骤
        if step_1_usb_audio(ssh):
            if step_2_install_app(ssh):
                step_3_boot_logo(ssh)
                
                # 4. 重启 
                print("\n正在重启设备...")
                exec_cmd(ssh, "reboot", ignore_error=True)
                
    except KeyboardInterrupt:
        print("\n用户取消操作")
    except Exception as e:
        print(f"\n发生未知错误: {e}")
    finally:
        ssh.close()