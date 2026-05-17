<p align="center">
  <img src="https://img.shields.io/badge/inkflow-Next--Gen_AI_Novel_Engine-8b5cf6?style=for-the-badge&logo=openai" alt="inkflow">
  <img src="https://img.shields.io/badge/UI-Modern_Glassmorphism-a78bfa?style=for-the-badge" alt="UI">
</p>

<h1 align="center">🖊 inkflow</h1>

<p align="center">
  <strong>多智能体协同的小说创作引擎：让长篇创作重获连贯与灵魂</strong><br>
  A Narrative Symphony Orchestrated by 7 Specialized AI Agents.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776ab?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/WebSocket-Realtime-orange?logo=socket.io&logoColor=white" alt="WebSocket">
  <img src="https://img.shields.io/badge/Agents-7_Specialized-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
</p>

---

## 🌟 为什么选择 inkflow?

**长篇小说创作最怕什么？** 逻辑断层、角色崩坏、伏笔遗忘、以及千篇一律的"AI 翻译味"。

**inkflow** 并不是一个简单的对话框，它是一个模拟 **顶级小说工作室** 的生产管线。它通过 7 个专业 Agent 的深度博弈与协作，确保你的故事从第 1 章到第 1000 章都拥有统一的灵魂。

### 核心黑科技
- 🧠 **动态长效记忆**：不再依赖 LLM 脆弱的上下文窗口，通过"真相文件 (Truth Files)"持久化存储世界观、角色弧线与万字伏笔池。
- 🎭 **7 智能体管线**：从战略布局到逐字润色，每个环节都有专家 Agent 把关。
- 🛡️ **去 AI 味引擎**：内置深度审校模型，自动识别并重写 40+ 类 AI 常用废话，注入风格指纹。
- 🧪 **文风蒸馏系统**：只需上传样章，即可"克隆"特定作者的叙事节奏与遣词造句习惯。

---

## ✨ 核心特性一览

### 1. 7-Agent 协同管线 (The Pipeline)
基于 **WebSocket** 的实时进度流，你可以亲眼看到故事是如何诞生的：
- 🎯 **Strategist (战略师)**: 掌控全局节奏，决定章节的情绪走向。
- 📋 **Prophet (大纲师)**: 滚动规划未来 5 章的大纲，确保逻辑不跑偏。
- 🔧 **Compose (编排师)**: 从万字内存中提取最相关的"真相片段"喂给写手。
- ✍️ **Writer (写手)**: 拒绝水文！根据风格指纹输出极具感染力的正文。
- 🔍 **Editor (编辑)**: 双层审计（代码层 + LLM 层），不合格？重写！
- 👁 **Observer (观察者)**: 实时提取新出现的角色、物品与伏笔。
- 📚 **Librarian (图书管理员)**: 自动更新世界设定，维护记忆的绝对权威。

### 2. 双层审计系统 (Dual-Layer Audit)
**代码层（零 Token 消耗）**：
- 角色状态一致性：死亡角色不应再出场
- 资源连续性：消耗物品不应凭空出现
- 伏笔生命周期：过期伏笔自动告警
- 信息边界：角色不应知道他不该知道的事
- 破折号控制：每章最多 4 个，自动清理多余

**LLM 层（创意质量评估）**：
- 风格一致性、情节逻辑、情感表达、节奏感、对话自然度、描写质量、伏笔巧妙度

### 3. 真相文件系统 (World State)
系统的"故事大脑"，包含：
- **角色档案**: 自动追踪性格转变与状态（受伤、黑化等）。
- **关系图谱**: 动态维护角色间的恩怨情仇。
- **伏笔池**: 埋下的每一个坑，系统都会在合适的时机提醒你填上。
- **资源账本**: 武器、功法、金钱？系统帮你算得清清楚楚。
- **情绪弧线**: 追踪每个角色的情感变化。
- **信息边界**: 记录每个角色知道什么、不知道什么。

### 4. 全新的 Glassmorphism Web UI
深度优化的沉浸式创作界面：
- **实时看板**: 监控所有 Agent 的思考状态与生成进度。
- **沉浸式工作台**: 三栏布局，左手查阅记忆，右手实时审校，中间专注创作。
- **角色关系图谱**: 可视化角色之间的关系网络。
- **伏笔追踪面板**: 实时监控伏笔状态（待收/已收/过期）。
- **章节对比**: 初稿 vs 终稿对比，一键重写已保存章节。

### 5. 全自动模式
- 🤖 **一键生成多章**: 输入章节数，无人值守自动创作。
- ⚡ **智能重写**: 质量不达标自动重写（最多 2 次）。
- 📊 **实时进度**: WebSocket 推送每章生成状态。

### 6. 文风蒸馏系统
- 📖 **风格分析**: 上传样章，6 维度深度分析写作风格。
- 🧬 **风格克隆**: 自动生成 5 种定制 Agent Skill（写手、战略师、大纲师、编辑、图书管理员）。
- 🔄 **风格融合**: 多本书风格融合，创造独特写作风格。

---

## 🚀 快速启动

### 安装环境

推荐使用 [uv](https://github.com/astral-sh/uv) 极速同步环境：

```bash
git clone https://github.com/real-Elysia886/inkflow.git
cd inkflow
uv sync
```

### 启动创作引擎

```bash
python main.py
```
访问 `http://127.0.0.1:8000` 即可开启你的创作之旅。

> **首次使用**：进入 **模型配置** 页面，添加 LLM Provider（如 OpenAI、DeepSeek）并填入 API Key。

### Docker 部署

```bash
git clone https://github.com/real-Elysia886/inkflow.git
cd inkflow
docker-compose up -d --build
```

访问 `http://你的服务器IP:8000`，在 **模型配置** 页面添加 Provider 并填入 API Key 即可。

```bash
# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

---

## 🛠 架构逻辑

```mermaid
graph TB
    subgraph 输入层["📥 输入层"]
        A[作者意图 / 关键词] --> B[快速入门向导]
        C[大纲编辑] --> D[大纲窗口]
        E[章节导入] --> F[文本提取]
    end

    subgraph 调度层["⚙️ 调度层"]
        G{ChapterPipeline}
        H[WebSocket 实时推送]
        I[Job 队列管理]
    end

    subgraph 智能体层["🤖 7-Agent 协同管线"]
        J["🎯 Strategist<br/>战略师<br/><i>全局节奏规划</i>"]
        K["📋 Prophet<br/>大纲师<br/><i>滚动5章大纲</i>"]
        L["🔧 Compose<br/>编排师<br/><i>上下文组装</i>"]
        M["✍️ Writer<br/>写手<br/><i>正文撰写</i>"]
        N["🔍 Editor<br/>编辑<br/><i>双层审计</i>"]
        O["👁 Observer<br/>观察者<br/><i>事实提取</i>"]
        P["📚 Librarian<br/>图书管理员<br/><i>归档更新</i>"]
    end

    subgraph 记忆层["🧠 记忆层 (Truth Files)"]
        Q[(World State)]
        R[角色档案]
        S[关系图谱]
        T[伏笔池]
        U[资源账本]
        V[情绪弧线]
        W[情节线]
        X[RAG 索引]
    end

    subgraph 输出层["📤 输出层"]
        Y[章节正文]
        Z[审校报告]
        AA[流式输出]
        AB[人工反馈]
    end

    subgraph 前端层["🖥 前端层"]
        BC[一键生成页面]
        BD[章节库]
        BE[作家工作台]
        BF[世界设定]
        BG[模型配置]
    end

    B --> G
    D --> G
    F --> G
    G --> H
    G --> I

    I --> J
    J --> K
    K --> L
    L --> M
    M --> N
    N --> O
    O --> P

    J -.->|规划| Q
    K -.->|大纲| Q
    L -.->|检索| X
    M -.->|风格| Q
    N -.->|评估| Q
    O -.->|提取| Q
    P -.->|更新| Q

    Q --- R
    Q --- S
    Q --- T
    Q --- U
    Q --- V
    Q --- W
    Q --- X

    P --> Y
    N --> Z
    M --> AA
    AB --> Q

    H --> BC
    Y --> BD
    Y --> BE
    Q --> BF
    Q --> BG

    style G fill:#8b5cf6,stroke:#fff,stroke-width:2px,color:#fff
    style Q fill:#10b981,stroke:#fff,stroke-width:2px,color:#fff
    style H fill:#f59e0b,stroke:#fff,stroke-width:2px,color:#fff
    style M fill:#3b82f6,stroke:#fff,stroke-width:2px,color:#fff
    style N fill:#ef4444,stroke:#fff,stroke-width:2px,color:#fff

    classDef agentStyle fill:#1e1b4b,stroke:#8b5cf6,stroke-width:2px,color:#fff
    class J,K,L,M,N,O,P agentStyle

    classDef memStyle fill:#064e3b,stroke:#10b981,stroke-width:1px,color:#a7f3d0
    class R,S,T,U,V,W,X memStyle

    classDef ioStyle fill:#1e293b,stroke:#64748b,stroke-width:1px,color:#e2e8f0
    class A,C,E,Y,Z,AA,AB ioStyle

    classDef uiStyle fill:#312e81,stroke:#818cf8,stroke-width:1px,color:#c7d2fe
    class BC,BD,BE,BF,BG uiStyle
```

---

## ⚙️ 模型配置建议

inkflow 支持为不同角色路由配置不同的 LLM 模型，以平衡质量、速度和成本。以下是推荐配置：

### 角色路由与模型推荐

| 角色 | 用途 | 推荐模型等级 | 温度 | Max Tokens | 说明 |
|------|------|-------------|------|------------|------|
| **Strategist** (战略师) | 全局节奏规划 | 高质量 | 0.3 | 4096 | 需要强推理能力，决定故事走向 |
| **Prophet** (大纲师) | 章节大纲生成 | 高质量 | 0.4 | 4096 | 需要逻辑一致性，规划未来5章 |
| **Writer** (写手) | 正文撰写 | 平衡 | 0.8 | 8192 | 需要创意和流畅度，温度可适当提高 |
| **Editor** (编辑) | 质量审校 | 高质量 | 0.2 | 4096 | 需要精准判断，温度要低 |
| **Observer** (观察者) | 事实提取 | 快速 | 0.3 | 2048 | 结构化提取，不需要创意 |
| **Reflector** (反思者) | 事实写入 | 快速 | 0.2 | 2048 | 结构化操作，不需要创意 |
| **Librarian** (图书管理员) | 章节摘要 | 快速 | 0.3 | 2048 | 摘要生成，不需要创意 |

### 模型选择策略

#### 高质量模型（推荐用于关键角色）
适用于 Strategist、Prophet、Editor 等需要强推理和精准判断的角色。

#### 平衡模型（推荐用于创意角色）
适用于 Writer 等需要创意和流畅度的角色。

#### 快速模型（推荐用于结构化任务）
适用于 Observer、Reflector、Librarian 等执行结构化操作的角色。

### 参数设置建议

| 参数 | 规划/大纲 | 正文撰写 | 质量审校 | 事实提取 |
|------|----------|----------|----------|----------|
| **温度** | 0.2-0.4 | 0.7-0.9 | 0.1-0.3 | 0.2-0.4 |
| **Max Tokens** | 2048-4096 | 4096-8192 | 2048-4096 | 1024-2048 |

---

## 🤝 愿景

我们相信，AI 不应替代作者的想象力，而应作为**全能的助手**，去处理繁琐的设定对齐与质量自检，让作者专注于那一瞬间的灵感迸发。

欢迎提交 PR 或 Issue。让我们一起构建全球最懂小说家的创作框架！

**License**: MIT
