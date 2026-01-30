import paramiko
from scp import SCPClient
import os
import glob
import time
import sys
import serial
import threading
import itertools
import serial.tools.list_ports


# ================= 基础配置 =================
# 设备默认IP 
DEVICE_IP = '192.168.1.2' 
SSH_PORT = 22
USERNAME = 'root'
PASSWORD = 'root' 
# 远程临时目录 (/dev/shm)
REMOTE_TEMP = '/dev/shm' 

# 串口配置
SERIAL_PORT = 'COM9'
BAUDRATE = 115200
SERIAL_PORT_CONNECT_TIMEOUT = True  

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

class LoadingSpinner:
    def __init__(self, message="Loading...", delay=0.1):
        self.message = message
        self.delay = delay
        self.stop_running = False
        self.screen_lock = threading.Lock()
        
    def spinner_task(self):
        spinner = itertools.cycle(['|', '/', '-', '\\'])
        while not self.stop_running:
            with self.screen_lock:
                sys.stdout.write(f'\r{next(spinner)} {self.message}')
                sys.stdout.flush()
            time.sleep(self.delay)
            
        # 清除最后一行
        sys.stdout.write('\r' + ' ' * (len(self.message) + 2) + '\r')
        sys.stdout.flush()

    def __enter__(self):
        self.stop_running = False
        self.thread = threading.Thread(target=self.spinner_task)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_running = True
        self.thread.join()

        if exc_type is None:
            sys.stdout.write(f' {self.message} success\n')
        elif not SERIAL_PORT_CONNECT_TIMEOUT:
            sys.stdout.write(f' {self.message} FAILED\n')


def run_cmd_verbose(ssh, cmd):
    """
    辅助函数：执行命令并打印返回码、标准输出和错误信息
    """
    print(f"\n[执行命令] {cmd}")
    
    # Paramiko 的标准执行方式
    stdin, stdout, stderr = ssh.exec_command(cmd)
    
    # 阻塞直到命令执行完毕，获取退出状态码 (Exit Code)
    exit_status = stdout.channel.recv_exit_status()
    
    # 获取输出内容
    out_msg = stdout.read().decode().strip()
    err_msg = stderr.read().decode().strip()

    # 打印返回码
    print(f"  └─ [返回码]: {exit_status}")

    # 如果有输出，打印出来方便调试
    if out_msg:
        print(f"  └─ [标准输出]: {out_msg[:200]}..." if len(out_msg)>200 else f"  └─ [标准输出]: {out_msg}")
    
    # 如果出错（返回码不为0），打印错误信息
    if exit_status != 0:
        print(f"  └─ [ 错误信息]: {err_msg}")
        return False
    
    return True



def create_ssh_client():
    """创建 SSH 连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        with LoadingSpinner(f" 正在连接到设备 {DEVICE_IP}..."):
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
    print(f" 发现应用包: {os.path.basename(latest_file)}")
    return latest_file

def step_1_usb_audio(ssh):
    """
    步骤 4.2.2: ss528v100增加USB音频 
    """
    with LoadingSpinner(f"[1/4] 安装 USB 音频补丁..."):
    
        if not os.path.exists(LOCAL_AUDIO_PATH):
            print(f"本地补丁目录不存在: {LOCAL_AUDIO_PATH}")
            return False

    with LoadingSpinner(f" 上传音频补丁文件..."):
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
            "addgroup audio || true"
        ]
        
        for cmd in commands:
            if not exec_cmd(ssh, cmd):
                return False
            
    print("   USB 音频补丁安装成功")

    print("WARNING:重启设备以生效配置")
    # 发送 reboot 命令，ignore_error=True 防止因连接立即断开而报错
    exec_cmd(ssh, "reboot", ignore_error=True)
    return True

def step_2_install_app(ssh):
    """
    步骤 4.2.3: 应用安装
    """
    local_pkg = find_app_package()
    pkg_name = os.path.basename(local_pkg)
    print(f"\n[2/4] 安装应用: {pkg_name} ")
    
    remote_file_path = f"{REMOTE_TEMP}/{pkg_name}"

    with LoadingSpinner(f" 正在上传应用安装包..."):
        try:
            with SCPClient(ssh.get_transport()) as scp:
                scp.put(local_pkg, remote_file_path)
        except Exception as e:
            print(f"上传过程发生异常: {e}")
            return False

    # ================= 验证上传是否成功 =================
    with LoadingSpinner(f" 正在验证上传结果..."):
    # 使用 ls -l 查看文件是否存在，exec_cmd 如果返回 False 说明文件没找到
        if not exec_cmd(ssh, f"ls -l {remote_file_path}"):
            print(f"错误: 远程文件验证失败，{pkg_name} 未成功上传！")
            return False
    # =========================================================
    with LoadingSpinner(f" 执行应用安装脚本..."):

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
            if not run_cmd_verbose(ssh, cmd):
                return False

    print("WARNING:重启设备以生效配置")           
    return True

def step_3_boot_logo(ssh):
    """
    步骤 4.2.5: 开机画面设置 (Linux)
    """
    with LoadingSpinner(f"[3/4]设置开机画面..."):
    
        # 源文件在设备上的 /app/dt/cfg/
        commands = [
            "cp /app/dt/cfg/bootlogo-hg.jpg /recovery/bootlogo.jpg",
            "dd if=/recovery/bootlogo.jpg of=/dev/mmcblk0p4 bs=1024"
        ]
    
    for cmd in commands:
        if not exec_cmd(ssh, cmd):
            return False
            
    print(f"开机画面设置成功 \nWARNING:还需要在Uboot设置参数")
    return True

def wait_for_device_online(timeout=300):
    """等待设备上线 (用于烧录完后自动衔接)"""
    with LoadingSpinner(f" 等待设备 {DEVICE_IP} 上线...", delay=0.5):
        start = time.time()
        while time.time() - start < timeout:
            response = os.system(f"ping -n 1 -w 1000 {DEVICE_IP} > nul")
            if response == 0:
                #print("设备已上线")
                time.sleep(5) # 等待 SSH 服务启动
                return True
            time.sleep(2)
    print("等待超时，设备未上线")
    return False

def step_4_uboot_settings(serial_port):
    """通过串口修改 U-Boot 环境变量"""

    input("修改设备信息后，按回车继续...")
    print("\n正在重启设备...")
    exec_cmd(ssh, "reboot", ignore_error=True)
    
    with LoadingSpinner(" 连接串口..."):
        try:
            # 尝试打开串口
            ser = serial.Serial(serial_port, BAUDRATE, timeout=0.1)
        except serial.SerialException as e:

            print(f"\n 串口错误: 无法打开 {serial_port}")
            print(f"   原因: {e}")
            
            # 自动列出当前存在的串口，帮用户找原因
            print("\n 当前电脑上实际存在的串口如下：")
            existing_ports = list(serial.tools.list_ports.comports())
            if not existing_ports:
                print("   (空) 未检测到任何串口设备，请检查 USB 线是否插好")
            else:
                for p in existing_ports:
                    print(f"   -> {p.device} ({p.description})")
            
            print("\n 建议：")
            print("   1. 请检查 USB 线是否松动。")
            print("   2. 如果端口号变了，请重新运行脚本并选择正确的号码。")
            return False


    with LoadingSpinner(f"[4/4] 通过串口{serial_port}修改 U-Boot 参数..."):
        
        try:
            print(f"  \n串口已打开，正在等待设备重启...")
            
            start_time = time.time()
            interrupted = False
            
            # 1. 拦截阶段
            while time.time() - start_time < 60: 
                ser.write(b'\n') # 发送回车
                
                if ser.in_waiting:
                    try:
                        #raw_data = ser.read(ser.in_waiting)
                        output = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                        output_lower = output.lower()
                        if "stop autoboot" in output_lower:
                            ser.write(b'\n\n\n\n\n\n')
                            time.sleep(0.05)

                        # 如果检测到 U-Boot 提示符
                        if "#" in output:
                            ser.write(b'\n\n\n\n')
                            time.sleep(0.5)
                            ser.read_all()
                            interrupted = True
                            print("\n\n进入 U-Boot 命令行")
                            break
                    except:
                        pass
                
                # 打印一个小点表示正在运行
                sys.stdout.write(".")
                sys.stdout.flush()
                time.sleep(0.5)
                
            if not interrupted:
                SERIAL_PORT_CONNECT_TIMEOUT = False
                print(f"\n 失败: 超时未检测到 U-Boot 提示符。")
                print("   可能原因: 串口线接错了(TX/RX接反)，或者设备启动太快已进入系统。")
                ser.close()
                return False

            # 2. 命令
            cmds = [
                'setenv bootcmd "setvobg 0 0; run run_logo; run update_script;"',
                'saveenv',
                'reset'
            ]
            
            for cmd in cmds:
                ser.write((cmd + "\n").encode('utf-8'))
                time.sleep(1) # 等待写入
                
                # 简单的回显清理
                if ser.in_waiting:
                    ser.read(ser.in_waiting)
            
            print(" U-Boot 参数修改完成，设备正在重启。")
            ser.close()
            return True

        except Exception as e:
            print(f"\n未知错误: {e}")
            if ser.is_open:
                ser.close()
            return False

# ================= 主程序 =================
if __name__ == "__main__":
    print(f"当前工作目录: {BASE_DIR}")
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
            print("\n设备重启中，断开当前 SSH 连接...")
            ssh.close() # 主动关闭旧连接
            
            # --- 等待重启并重连 ---
            with LoadingSpinner("等待设备重启..."):
                time.sleep(10) # 等待几秒，避开设备刚关机时的 Ping 通假象
            
            if wait_for_device_online(timeout=120):
                with LoadingSpinner("重新连接设备..."):
                    ssh = create_ssh_client() # 【创建新连接】
                
                if ssh:
                    if step_2_install_app(ssh):
                        print("\n 正在重启设备以应用配置...")
                        exec_cmd(ssh, "reboot", ignore_error=True)
                        ssh.close()
                         # --- 等待重启并重连 ---
                        with LoadingSpinner("等待设备重新连接..."):
                            time.sleep(10)
                        
                        if wait_for_device_online(timeout=120):
                            with LoadingSpinner("重新连接设备..."):
                                ssh = create_ssh_client() # 【创建新连接】
                            
                            if ssh:
                                if step_3_boot_logo(ssh):                    
                                    step_4_uboot_settings(SERIAL_PORT)
                
    except KeyboardInterrupt:
        print("\n用户取消操作")
    except Exception as e:
        print(f"\n发生未知错误: {e}")
    finally:
        if 'ssh' in locals() and ssh is not None:
            try:
                ssh.close()
                print(" SSH 连接已关闭")
            except Exception:
                pass