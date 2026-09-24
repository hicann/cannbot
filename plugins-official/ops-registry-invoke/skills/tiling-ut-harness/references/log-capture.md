# OP_LOGE 日志捕获

负例（GRAPH_FAILED）case 的断言对象是日志锚点——TilingFunc 里 OP_LOGE 打的错误串。两个前提不满足时，UT 里什么日志都看不到，断言必挂。

## 前提 1：环境变量（run.sh 导出，缺一不可）

```bash
export ASCEND_SLOG_PRINT_TO_STDOUT=1   # slog 默认写 ~/ascend/log/ 文件，此变量把它改道 stdout/stderr
export ASCEND_GLOBAL_LOG_LEVEL=3       # 3=ERROR，压掉驱动 DEBUG 噪声
```

开启后 OP_LOGE 的输出格式是 `[ERROR] OP(...):...` 开头（输出里可能夹杂 `CheckLogLevel` 等库内杂行，grep 断言时排除或直接锚定 OP_LOGE 格式前缀）。

不设变量时日志只进 `~/ascend/log/`（debug/run/security/atrace 子目录），fd 重定向抓不到。

## 前提 2：进程内重定向（UT 按 case 捕获）

gtest 的每 case 断言需要"只抓这一次调用产生的日志"。CANN slog 直接写 fd 1/2，不走 C++ stream，所以必须 dup2 级重定向。RAII 模板：

```cpp
class LogCapture {
public:
    LogCapture() {                       // 构造 = 开始捕获
        (void)fflush(stdout); (void)fflush(stderr);
        std::vector<char> tmpl("/tmp/tiling_ut_XXXXXX"); tmpl.push_back('\0');
        const int fd = ::mkstemp(tmpl.data());
        path_ = tmpl.data();
        saved_out_ = ::dup(1); saved_err_ = ::dup(2);
        if (fd >= 0) { (void)::dup2(fd, 1); (void)::dup2(fd, 2); (void)::close(fd); active_ = true; }
    }
    ~LogCapture() {                      // 析构 = 恢复 fd
        if (active_) { (void)::dup2(saved_out_, 1); (void)::dup2(saved_err_, 2); }
        (void)::close(saved_out_); (void)::close(saved_err_);
    }
    std::string Read() const { /* open(path_) 循环 read 拼接返回 */ }
private:
    int saved_out_ = -1, saved_err_ = -1; bool active_ = false; std::string path_;
};
```

用法：`{ LogCapture cap; tilingFunc(ctx); if (expect_fail) EXPECT_NE(cap.Read().find("<anchor>"), std::string::npos); }`——构造/析构即作用域边界，RAII 保证 fd 恢复。

**适用限定**：本模板验证于同步 ERROR 输出配置（ASCEND_GLOBAL_LOG_LEVEL=3），假设 OP_LOGE 在 capture 作用域内同步落到 fd 1/2。若 slog 运行在异步刷写配置，作用域结束后的日志会落到恢复后的 fd 上，表现为"LogCapture 内抓不到锚点且重跑结果漂移"——先查 slog 异步相关环境变量/配置，再怀疑锚点串本身；这与 TilingData 脏缓冲的间歇性失败症状相似，修法相反（此处查日志配置，那边 memset 缓冲）。

## 锚点纪律

- 锚点串由被测方提供：实现 task 的 stub/正文在 OP_LOGE 里写稳定子串（如 `"context is nullptr"`），UT 断言它。设计文档 Validation.md 的异常行为是锚点的来源，UT 与实现各自引用，不硬编码对端字符串。
- 断言用 `find(anchor) != npos`，不整行比对（时间戳/PID 段每次不同）。
- dlopen 的 op_host .so 内 OP_LOGE 同样受这两个环境变量控制——在 run.sh 导出，不在 UT 里 setenv（UT 启动前 dlopen 已可能发生）。
