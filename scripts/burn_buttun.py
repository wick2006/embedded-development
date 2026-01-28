import win32gui
import win32con
import win32api
import pyautogui
import time
import sys

# ================= 配置区域 =================
# 1. 填入校准好的坐标偏移量 (必须填!)
OFFSET_X = 170    # <--- 替换这里 (例如 850)
OFFSET_Y = 348    # <--- 替换这里 (例如 420)

# 2. 窗口标题关键词 (越准越好)
WINDOW_TITLE_KEY = "ToolPlatform" 
# ===========================================

def find_window_hwnd(keyword):
    """
    使用 Win32 API 快速查找窗口句柄 (0延迟)
    """
    hwnd_list = []
    
    # 定义回调函数，遍历所有窗口
    def enum_handler(hwnd, ctx):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if keyword.lower() in title.lower():
                hwnd_list.append((hwnd, title))
    
    win32gui.EnumWindows(enum_handler, None)
    
    if not hwnd_list:
        return None, None
    
    # 返回找到的第一个窗口 (句柄, 标题)
    return hwnd_list[0]

def activate_window(hwnd):
    """强制置顶窗口"""
    try:
        # 如果窗口最小化了，还原它
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        
        # 尝试置顶
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass

def auto_burn_instant():
    if OFFSET_X == 0 and OFFSET_Y == 0:
        print("❌ 错误：请填入 OFFSET_X 和 OFFSET_Y！(也就是您第一步测出来的坐标)")
        return

    print(f"⚡ 光速版脚本已启动 | 目标: {WINDOW_TITLE_KEY}")
    print("------------------------------------------------")
    print("不用等待连接，直接按回车即可！")

    while True:
        try:
            # 1. 等待指令
            cmd = input("\n👉 请插板子并按回车 (q退出): ")
            if cmd.lower() == 'q': break

            # 2. 毫秒级查找窗口
            hwnd, title = find_window_hwnd(WINDOW_TITLE_KEY)
            
            if not hwnd:
                print("❌ 找不到窗口，请检查软件是否打开！")
                continue

            # 3. 激活窗口
            activate_window(hwnd)
            
            # 4. 获取窗口当前的绝对坐标 (Left, Top, Right, Bottom)
            rect = win32gui.GetWindowRect(hwnd)
            window_left, window_top = rect[0], rect[1]

            # 5. 计算点击位置
            click_x = window_left + OFFSET_X
            click_y = window_top + OFFSET_Y

            # 6. 执行点击
            pyautogui.click(click_x, click_y)
            print(f"✅ 已点击! (窗口位置: {window_left},{window_top})")
            
            # 7. 防抖延时
            time.sleep(1) # 稍微等一下，防止连点

        except KeyboardInterrupt:
            sys.exit()
        except Exception as e:
            print(f"⚠️ 发生错误: {e}")

if __name__ == "__main__":
    auto_burn_instant()