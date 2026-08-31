const pluginData = {
  "ops-direct-invoke": {
    domain: "算子领域",
    title: "算子生成",
    lede: "使用完整的 Ascend C Kernel 直调算子开发工作流，从需求分析、方案设计和实现推进到精度与性能验收。",
    callout: "该工作流会安装关联 Skills、Agents、权限配置和依赖仓，首次安装耗时可能略长。",
    prompt: "请使用 ops-direct-invoke 工作流，根据当前项目中的算子需求生成完整的 Ascend C Kernel 直调算子。先分析需求和运行环境，再完成方案设计、代码实现、测试、精度与性能验收。",
    next: "ascendc-st-design",
  },
  "ascendc-st-design": {
    domain: "算子领域",
    title: "算子测试",
    lede: "基于 aclnn 接口文档完成参数定义、测试因子提取、约束分析及 L0/L1/L2 系统测试用例设计。",
    callout: "请准备算子的 REQUIREMENTS.md 和 aclnn 接口文档。生成脚本需要 Python 3，以及 PyYAML、NumPy 和 pandas。",
    prompt: "使用 ascendc-st-design skill，为当前项目的 add_rms_norm Ascend C 算子设计 L0/L1/L2 系统测试（ST）用例。基于 REQUIREMENTS.md 和 aclnn 接口文档完成参数定义、测试因子提取与约束分析，并在 operators/add_rms_norm/tests/st/ 下生成用例和覆盖报告。",
    next: "model-infer-optimize",
  },
  "model-infer-optimize": {
    domain: "模型领域",
    title: "模型迁移与推理优化",
    lede: "把 PyTorch 模型迁移到昇腾 NPU，并完成精度对齐、性能分析和推理优化。",
    callout: "工作流会先建立可复现的 CPU 基线，再处理不支持算子、设备适配、精度与性能问题。",
    prompt: "使用 model-infer-optimize，把当前 PyTorch 模型迁移到昇腾 NPU 推理。先建立 CPU 基线，再处理不支持算子和设备适配，最后完成精度对齐、性能分析和优化，并输出可复现的验证命令。",
    next: "ops-direct-invoke",
  },
};

const toolLabels = { opencode: "OpenCode", codex: "Codex", claude: "Claude Code", trae: "TRAE", dsh: "DSH" };
let selectedTool = "opencode";

async function copyText(text) {
  let copied = false;
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch (_) {}
  }
  if (!copied) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.cssText = "position:fixed;opacity:0;pointer-events:none";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      copied = document.execCommand("copy");
    } catch (_) {}
    textarea.remove();
  }
  const toast = document.getElementById("toast");
  if (!toast) return copied;
  toast.textContent = copied ? "内容已复制" : "复制失败，请手动复制";
  toast.classList.add("show");
  window.clearTimeout(copyText.timer);
  copyText.timer = window.setTimeout(() => toast.classList.remove("show"), 1800);
  return copied;
}

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;
    const originalText = button.dataset.copyLabel || button.textContent;
    button.dataset.copyLabel = originalText;
    const copied = await copyText(target.textContent.trim());
    button.textContent = copied ? "已复制" : "复制失败";
    button.classList.toggle("copied", copied);
    window.clearTimeout(button.copyTimer);
    button.copyTimer = window.setTimeout(() => {
      button.textContent = originalText;
      button.classList.remove("copied");
    }, 1600);
  });
});

const landingTranslations = {
  en: {
    "hero-title": "AI-powered innovation for the CANN ecosystem",
    "hero-lede-one": "CANNBot provides composable Agent workflows for operator and model development.",
    "hero-lede-two": "Make operator generation, operator testing, and model migration capabilities that your Agent can invoke directly.",
    "view-gitcode": "View GitCode",
    "plugin-docs": "Plugin docs",
    "plugin-title": "Make Agents the new productivity layer for CANN development",
    "plugin-lede": "Drive professional workflows with natural language, from operator development and testing to model migration, and make complex CANN engineering easier.",
    "ops-domain": "Operators",
    "model-domain": "Models",
    "card-one-title": "Operator generation",
    "card-one-lede": "Migrate CUDA operators to Ascend C, from analysis and design through development and validation.",
    "card-one-meta": "Full workflow",
    "card-two-title": "Operator testing",
    "card-two-lede": "Use aclnn interface documentation to define parameters, extract test factors, analyze constraints, and design L0/L1/L2 system test cases.",
    "card-two-meta-one": "Standalone Skill",
    "card-two-meta-two": "System testing",
    "card-three-title": "Model migration & inference optimization",
    "card-three-lede": "Establish a baseline, adapt devices, then complete precision alignment, performance analysis, and inference optimization.",
    "card-three-meta-one": "Model migration",
    "card-three-meta-two": "Performance",
    "demo-title": "See the complete operator generation workflow",
    "demo-lede": "From plugin installation to Agent invocation, see how CANNBot carries an operator generation task forward.",
    "workflow-title": "Minimal setup,<br />ready for CANN development.",
    "workflow-lede": "Connect CANNBot with one command and give your Agent professional workflows it can invoke directly. Visit the plugin docs for complete installation and usage guides.",
    "workflow-docs": "View plugin docs",
    "step-one-title": "Install",
    "step-one-lede": "Connect Skills, Agents, and client configuration automatically.",
    "step-two-title": "Start your client",
    "step-two-lede": "Open the Agent you already know in the current project.",
    "step-three-title": "Describe the goal",
    "step-three-lede": "Use natural language to start the complete engineering workflow.",
    copied: "Command copied",
  },
};

function setupLandingLanguage() {
  if (!document.querySelector(".landing-page")) return;
  const elements = [...document.querySelectorAll("[data-i18n], [data-i18n-html]")];
  const defaults = new Map(elements.map((element) => [element, element.dataset.i18nHtml ? element.innerHTML : element.textContent]));
  const title = document.title;
  const description = document.querySelector('meta[name="description"]');

  const applyLanguage = (language) => {
    const english = language === "en";
    document.documentElement.lang = english ? "en" : "zh-CN";
    document.title = english ? "CANNBot · AI-powered CANN ecosystem innovation" : title;
    if (description) description.content = english
      ? "CANNBot plugin portal for composable Agent workflows in operator and model development."
      : "CANNBot 插件门户，为算子与模型开发提供可组合的 Agent 工作流。";

    elements.forEach((element) => {
      const key = element.dataset.i18n || element.dataset.i18nHtml;
      const value = english ? landingTranslations.en[key] : defaults.get(element);
      if (element.dataset.i18nHtml) element.innerHTML = value;
      else element.textContent = value;
    });
    document.querySelectorAll("[data-lang-switch]").forEach((button) => {
      const active = button.dataset.langSwitch === language;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    try { window.localStorage.setItem("cannbot-language", language); } catch (_) {}
  };

  let initialLanguage = "zh";
  try { initialLanguage = window.localStorage.getItem("cannbot-language") || initialLanguage; } catch (_) {}
  applyLanguage(initialLanguage === "en" ? "en" : "zh");
  document.querySelectorAll("[data-lang-switch]").forEach((button) => {
    button.addEventListener("click", () => applyLanguage(button.dataset.langSwitch));
  });
}

setupLandingLanguage();

function installCommand(pluginId) {
  return `npx @cannbot-plugin/cannbot@latest install ${pluginId} --tool ${selectedTool}`;
}

function renderPluginPage() {
  const title = document.getElementById("article-title");
  if (!title) return;
  const requestedId = new URLSearchParams(window.location.search).get("id") || "ops-direct-invoke";
  const pluginId = pluginData[requestedId] ? requestedId : "ops-direct-invoke";
  const data = pluginData[pluginId];
  document.title = `${data.title} - CANNBot 插件文档`;
  title.textContent = data.title;
  document.getElementById("article-domain").textContent = data.domain;
  document.getElementById("breadcrumb-domain").textContent = data.domain;
  document.getElementById("breadcrumb-title").textContent = data.title;
  document.getElementById("article-lede").textContent = data.lede;
  document.getElementById("article-callout").textContent = data.callout;
  document.getElementById("prompt-example").textContent = data.prompt;
  document.querySelectorAll("[data-plugin-link]").forEach((link) => link.classList.toggle("active", link.dataset.pluginLink === pluginId));
  const nextData = pluginData[data.next];
  document.getElementById("next-plugin").href = `./plugin.html?id=${data.next}`;
  document.getElementById("next-title").textContent = nextData.title;

  const updateCommand = () => {
    document.getElementById("install-command").textContent = installCommand(pluginId);
    document.getElementById("install-note").textContent = `安装器会自动识别当前目录，并写入 ${toolLabels[selectedTool]} 所需的 Skill 与 Agent 配置。`;
  };
  updateCommand();

  document.querySelectorAll("[data-doc-tool]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTool = button.dataset.docTool;
      document.querySelectorAll("[data-doc-tool]").forEach((item) => item.classList.toggle("active", item === button));
      updateCommand();
    });
  });
}

renderPluginPage();

const mobileMenu = document.getElementById("mobile-menu");
if (mobileMenu) mobileMenu.addEventListener("click", () => document.getElementById("docs-sidebar").classList.toggle("open"));

const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => entry.isIntersecting && entry.target.classList.add("revealed"));
}, { threshold: 0.12 });
document.querySelectorAll(".reveal").forEach((element) => observer.observe(element));

function startHeroMotion() {
  const canvas = document.getElementById("hero-canvas");
  if (!canvas) return;
  const context = canvas.getContext("2d");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pointer = { x: 0.56, y: 0.42, tx: 0.56, ty: 0.42, visible: false };
  const motes = Array.from({ length: 128 }, (_, index) => ({
    lane: index / 127,
    phase: Math.random() * Math.PI * 2,
    speed: 0.00008 + Math.random() * 0.0001,
    size: 0.45 + Math.random() * 1.4,
    alpha: 0.16 + Math.random() * 0.48,
  }));
  const meteors = Array.from({ length: 11 }, (_, index) => ({
    lane: 0.08 + (index / 10) * 0.84,
    phase: Math.random(),
    speed: 0.055 + Math.random() * 0.1,
    length: 150 + Math.random() * 150,
    alpha: 0.22 + Math.random() * 0.25,
    size: 0.8 + Math.random() * 0.8,
    bend: Math.random() * Math.PI * 2,
  }));
  const networkNodes = Array.from({ length: 34 }, () => ({
    x: 0.34 + Math.random() * 0.64,
    y: 0.16 + Math.random() * 0.62,
    phase: Math.random() * Math.PI * 2,
    drift: 8 + Math.random() * 18,
    size: 0.8 + Math.random() * 1.6,
  }));
  const pointerTrail = [];
  const orbit = document.querySelector(".hero-orbit");
  let width = 0;
  let height = 0;
  let ratio = 1;
  let ambientX = 0;
  let ambientY = 0;
  let frame = 0;

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = bounds.width;
    height = bounds.height;
    const orbitStyle = orbit ? window.getComputedStyle(orbit) : null;
    ambientX = orbitStyle ? Number.parseFloat(orbitStyle.left) : width * 0.66;
    ambientY = orbitStyle ? Number.parseFloat(orbitStyle.top) : height * 0.5;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function flowY(x, lane, time) {
    const spread = (lane - 0.5) * height * 0.44;
    const wave = Math.sin(x * 0.005 + time * 0.00045 + lane * 7) * (24 + lane * 22);
    const ripple = Math.sin(x * 0.012 - time * 0.00022 + lane * 13) * 9;
    return height * 0.43 + spread + wave + ripple;
  }

  function draw(time) {
    pointer.x += (pointer.tx - pointer.x) * 0.3;
    pointer.y += (pointer.ty - pointer.y) * 0.3;
    context.clearRect(0, 0, width, height);

    if (pointer.visible) {
      const trailPoint = { x: pointer.x * width, y: pointer.y * height, life: 1 };
      const previousPoint = pointerTrail[pointerTrail.length - 1];
      if (!previousPoint || Math.hypot(trailPoint.x - previousPoint.x, trailPoint.y - previousPoint.y) > 1.2) {
        pointerTrail.push(trailPoint);
      } else {
        previousPoint.x = trailPoint.x;
        previousPoint.y = trailPoint.y;
        previousPoint.life = 1;
      }
      if (pointerTrail.length > 22) pointerTrail.shift();
    }

    const halo = context.createRadialGradient(
      ambientX, ambientY, 0,
      ambientX, ambientY, Math.max(width, height) * 0.46,
    );
    halo.addColorStop(0, "rgba(42, 82, 158, 0.14)");
    halo.addColorStop(0.32, "rgba(21, 46, 92, 0.055)");
    halo.addColorStop(1, "rgba(7, 9, 13, 0)");
    context.fillStyle = halo;
    context.fillRect(0, 0, width, height);

    context.globalCompositeOperation = "lighter";
    for (let lane = 0; lane < 17; lane += 1) {
      const normalized = lane / 16;
      const fade = Math.sin(normalized * Math.PI);
      context.beginPath();
      for (let x = -30; x <= width + 30; x += 18) {
        const y = flowY(x + pointer.x * 25, normalized, time + pointer.y * 450);
        if (x === -30) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      context.strokeStyle = `rgba(${86 + lane * 2}, ${128 + lane * 2}, 220, ${0.006 + fade * 0.017})`;
      context.lineWidth = 0.7;
      context.stroke();
    }

    meteors.forEach((meteor) => {
      const travel = width + meteor.length * 2;
      const headX = ((meteor.phase * travel + time * meteor.speed) % travel) - meteor.length;
      const baseHeadY = flowY(headX, meteor.lane, time + meteor.bend * 140);
      const pointerX = pointer.x * width;
      const pointerY = pointer.y * height;
      const pointerDistance = Math.hypot(headX - pointerX, baseHeadY - pointerY);
      const attraction = Math.max(0, 1 - pointerDistance / 260);
      const headY = baseHeadY + (pointerY - baseHeadY) * attraction * 0.16;
      const segments = 22;

      for (let segment = segments; segment > 0; segment -= 1) {
        const tailRatio = segment / segments;
        const previousRatio = (segment - 1) / segments;
        const x1 = headX - meteor.length * tailRatio;
        const x2 = headX - meteor.length * previousRatio;
        const curveLift = attraction * 18 * Math.sin(tailRatio * Math.PI);
        const y1 = flowY(x1, meteor.lane, time + meteor.bend * 140) + (pointerY - baseHeadY) * attraction * 0.16 - curveLift;
        const y2 = flowY(x2, meteor.lane, time + meteor.bend * 140) + (pointerY - baseHeadY) * attraction * 0.16 - curveLift * 0.88;
        const intensity = (1 - tailRatio) ** 1.7;
        context.beginPath();
        context.moveTo(x1, y1);
        context.lineTo(x2, y2);
        context.strokeStyle = `rgba(116, 165, 255, ${meteor.alpha * intensity * (0.72 + attraction * 0.45)})`;
        context.lineWidth = 0.35 + intensity * meteor.size;
        context.stroke();
      }

      if (headX > -8 && headX < width + 8) {
        const glowRadius = 9 + attraction * 7;
        const glow = context.createRadialGradient(headX, headY, 0, headX, headY, glowRadius);
        glow.addColorStop(0, `rgba(220, 234, 255, ${0.72 + attraction * 0.08})`);
        glow.addColorStop(0.13, `rgba(137, 182, 255, ${0.52 + attraction * 0.12})`);
        glow.addColorStop(1, "rgba(84, 139, 240, 0)");
        context.fillStyle = glow;
        context.beginPath();
        context.arc(headX, headY, glowRadius, 0, Math.PI * 2);
        context.fill();
        context.beginPath();
        context.arc(headX, headY, meteor.size + attraction * 0.7, 0, Math.PI * 2);
        context.fillStyle = "rgba(232, 241, 255, .78)";
        context.fill();
      }
    });

    const points = networkNodes.map((node) => {
      const baseX = node.x * width + Math.sin(time * 0.00016 + node.phase) * node.drift;
      const baseY = node.y * height + Math.cos(time * 0.0002 + node.phase) * node.drift * 0.65;
      const deltaX = baseX - pointer.x * width;
      const deltaY = baseY - pointer.y * height;
      const distance = Math.hypot(deltaX, deltaY) || 1;
      const influence = Math.max(0, 1 - distance / 210);
      return {
        ...node,
        x: baseX + (deltaX / distance) * influence * 22,
        y: baseY + (deltaY / distance) * influence * 22,
        pointerDistance: distance,
      };
    });

    for (let first = 0; first < points.length; first += 1) {
      for (let second = first + 1; second < points.length; second += 1) {
        const distance = Math.hypot(points[first].x - points[second].x, points[first].y - points[second].y);
        if (distance > 145) continue;
        context.beginPath();
        context.moveTo(points[first].x, points[first].y);
        context.lineTo(points[second].x, points[second].y);
        context.strokeStyle = `rgba(94, 141, 231, ${(1 - distance / 145) * 0.105})`;
        context.lineWidth = 0.6;
        context.stroke();
      }
    }

    points.forEach((point) => {
      if (point.pointerDistance < 230) {
        context.beginPath();
        context.moveTo(point.x, point.y);
        context.lineTo(pointer.x * width, pointer.y * height);
        context.strokeStyle = `rgba(122, 167, 255, ${(1 - point.pointerDistance / 230) * 0.2})`;
        context.lineWidth = 0.7;
        context.stroke();
      }
      context.beginPath();
      context.arc(point.x, point.y, point.size, 0, Math.PI * 2);
      context.fillStyle = `rgba(133, 175, 255, ${0.18 + (1 - Math.min(1, point.pointerDistance / 230)) * 0.5})`;
      context.fill();
    });

    pointerTrail.forEach((point) => { point.life -= 0.034; });
    while (pointerTrail.length && pointerTrail[0].life <= 0) pointerTrail.shift();

    if (pointerTrail.length > 1) {
      const firstPoint = pointerTrail[0];
      const lastPoint = pointerTrail[pointerTrail.length - 1];
      const trailGradient = context.createLinearGradient(firstPoint.x, firstPoint.y, lastPoint.x, lastPoint.y);
      trailGradient.addColorStop(0, "rgba(77, 127, 225, 0)");
      trailGradient.addColorStop(0.55, "rgba(54, 133, 255, .08)");
      trailGradient.addColorStop(1, "rgba(115, 181, 255, .66)");
      const outerTrailGradient = context.createLinearGradient(firstPoint.x, firstPoint.y, lastPoint.x, lastPoint.y);
      outerTrailGradient.addColorStop(0, "rgba(41, 105, 240, 0)");
      outerTrailGradient.addColorStop(0.55, "rgba(41, 105, 240, .012)");
      outerTrailGradient.addColorStop(1, "rgba(41, 105, 240, .05)");
      const middleTrailGradient = context.createLinearGradient(firstPoint.x, firstPoint.y, lastPoint.x, lastPoint.y);
      middleTrailGradient.addColorStop(0, "rgba(52, 135, 255, 0)");
      middleTrailGradient.addColorStop(0.55, "rgba(52, 135, 255, .04)");
      middleTrailGradient.addColorStop(1, "rgba(52, 135, 255, .145)");

      const tracePointerPath = () => {
        context.beginPath();
        context.moveTo(firstPoint.x, firstPoint.y);
        for (let index = 1; index < pointerTrail.length - 1; index += 1) {
          const point = pointerTrail[index];
          const next = pointerTrail[index + 1];
          context.quadraticCurveTo(point.x, point.y, (point.x + next.x) / 2, (point.y + next.y) / 2);
        }
        context.lineTo(lastPoint.x, lastPoint.y);
      };

      tracePointerPath();
      context.strokeStyle = outerTrailGradient;
      context.lineWidth = 9.2;
      context.stroke();
      tracePointerPath();
      context.strokeStyle = middleTrailGradient;
      context.lineWidth = 3.7;
      context.stroke();
      tracePointerPath();
      context.strokeStyle = trailGradient;
      context.lineWidth = 1.08;
      context.shadowColor = "rgba(66, 148, 255, .7)";
      context.shadowBlur = 11.7;
      context.stroke();
      context.shadowBlur = 0;
    }

    if (pointer.visible) {
      const pointerX = pointer.x * width;
      const pointerY = pointer.y * height;
      const breath = 1 + Math.sin(time * 0.006) * 0.08;
      const pointerGlow = context.createRadialGradient(pointerX, pointerY, 0, pointerX, pointerY, 12.5 * breath);
      pointerGlow.addColorStop(0, "rgba(244, 248, 255, .78)");
      pointerGlow.addColorStop(0.16, "rgba(158, 196, 255, .52)");
      pointerGlow.addColorStop(0.48, "rgba(91, 146, 248, .12)");
      pointerGlow.addColorStop(1, "rgba(62, 116, 222, 0)");
      context.fillStyle = pointerGlow;
      context.beginPath();
      context.arc(pointerX, pointerY, 12.5 * breath, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = "rgba(248, 251, 255, .82)";
      context.beginPath();
      context.arc(pointerX, pointerY, 1.65, 0, Math.PI * 2);
      context.fill();
    }

    motes.forEach((mote) => {
      const progress = (mote.phase + time * mote.speed) % (Math.PI * 2);
      const x = ((progress / (Math.PI * 2)) * (width + 160)) - 80;
      const y = flowY(x, mote.lane, time);
      const edgeFade = Math.sin(Math.min(1, Math.max(0, x / width)) * Math.PI);
      context.beginPath();
      context.arc(x, y, mote.size, 0, Math.PI * 2);
      context.fillStyle = `rgba(132, 174, 255, ${mote.alpha * edgeFade})`;
      context.fill();
    });
    context.globalCompositeOperation = "source-over";
    if (!reduceMotion) frame = window.requestAnimationFrame(draw);
  }

  window.addEventListener("resize", resize);
  window.addEventListener("pointermove", (event) => {
    const bounds = canvas.getBoundingClientRect();
    const wasVisible = pointer.visible;
    pointer.tx = (event.clientX - bounds.left) / bounds.width;
    pointer.ty = (event.clientY - bounds.top) / bounds.height;
    pointer.visible = pointer.tx >= 0 && pointer.tx <= 1 && pointer.ty >= 0 && pointer.ty <= 1;
    if (pointer.visible && !wasVisible) {
      pointer.x = pointer.tx;
      pointer.y = pointer.ty;
      pointerTrail.length = 0;
    }
  }, { passive: true });
  window.addEventListener("blur", () => { pointer.visible = false; });
  resize();
  if (reduceMotion) draw(0);
  else frame = window.requestAnimationFrame(draw);
  window.addEventListener("pagehide", () => window.cancelAnimationFrame(frame), { once: true });
}

startHeroMotion();
