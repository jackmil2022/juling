---
name: react-native-dev
description: |
  React Native 和 Expo 开发指南，涵盖组件、样式、动画、导航、状态管理、表单、网络、性能优化、测试、本机功能和工程（项目结构、部署、SDK 升级、CI/CD）。使用场合：构建 React Native 或 Expo 应用程序、实现动画或本机 UI、管理状态、获取数据、编写测试、优化性能、部署到 App Store/Play Store、设置 CI/CD、升级 Expo SDK 或配置 Tailwind/NativeWind。
license: MIT
metadata:
  version: "1.0.0"
  category: mobile
  sources:
    - expo/skills by Expo (https://github.com/expo/skills) — Native UI, navigation, and animation patterns
    - Expo documentation (docs.expo.dev)
    - React Native documentation (reactnative.dev)
    - EAS (Expo Application Services) documentation
---

# React Native & Expo 开发指南

构建生产就绪的 React Native 和 Expo 应用程序的实用指南。涵盖 UI、动画、状态、测试、性能和部署。

＃＃ 参考

根据需要查阅这些资源：

- [references/navigation.md](references/navigation.md) — Expo Router：堆栈、选项卡、NativeTabs（`headerLargeTitle`、`headerBackButtonDisplayMode`）、链接、模式、工作表、上下文菜单
- [references/components.md](references/components.md) — FlashList 模式、`expo-image`、安全区域 (`contentInsetAdjustmentBehavior`)、本机控件、模糊/玻璃效果、存储
- [references/styling.md](references/styling.md) — StyleSheet、NativeWind/Tailwind、平台样式、主题、深色模式
- [references/animations.md](references/animations.md) — Reanimated 3：进入/退出、共享值、手势、滚动驱动
- [references/state-management.md](references/state-management.md) — Zustand（选择器、持久）、Jotai（原子、派生）、React 查询、上下文
- [references/forms.md](references/forms.md) — React Hook Form + Zod：验证、多步骤、动态数组
- [references/networking.md](references/networking.md) — 获取包装器、React 查询（乐观更新）、身份验证令牌、离线、API 路由、webhooks
- [references/performance.md](references/performance.md) — 分析工作流程、FlashList + `memo`、捆绑分析、TTI、内存泄漏、动画性能
- [references/testing.md](references/testing.md) — Jest、React Native 测试库、E2E 与 Maestro
- [references/native-capability.md](references/native-capabilities.md) — 相机、位置、权限（`use*Permissions` 挂钩）、触觉、通知、生物识别
- [references/engineering.md](references/engineering.md) — 项目布局（`components/ui/`、`stores/`、`services/`）、路径别名、SDK 升级、EAS 构建/提交、CI/CD、DOM 组件

## 快速参考

### 组件首选项

|目的|使用 |而不是 |
|--------|-----|------------|
|列表 | `FlashList` (`@shopify/flash-list`) + `memo` 项目 | `FlatList`（无视图回收）|
|图片 | `expo-image` | RN `<Image>`（无缓存，无 WebP）|
|新闻 | `Pressable` | `TouchableOpacity`（旧版）|
|音频| `expo-audio` | `expo-av`（已弃用）|
|视频 | `expo-video` | `expo-av`（已弃用）|
|动画 |复活3 | RN 动画 API（有限）|
|手势|手势处理程序 | PanResponder（旧版）|
|平台检查 | `process.env.EXPO_OS` | `Platform.OS` |
|背景 | `React.use()` | `React.useContext()`（反应 18）|
|安全区域滚动 | `contentInsetAdjustmentBehavior="automatic"` | `<SafeAreaView>` |
| SF 符号 | `expo-image` 与 `source="sf:name"` | `expo-symbols` |

### 扩大规模

|情况|考虑|
|------------|----------|
|带有滚动卡顿的长列表 |虚拟化列表库（例如 FlashList）|
|想要顺风式课程 |原生风 v4 |
|高频存储读取|基于同步的存储（例如 MMKV）|
|世博会新项目|裸露的 React 导航上的 Expo Router |

### 状态管理

|状态类型 |解决方案 |
|------------|----------|
|本地 UI 状态 | `useState` / `useReducer` |
|共享应用程序状态 | Zustand 或 Jotai |
|服务器/异步数据|反应查询 |
|表格状态 | React Hook 形式 + Zod |

### 性能优先级

|优先|问题 |修复 |
|----------|-----|-----|
|关键 |长列表卡顿 | `FlashList` + 已记住的项目 |
|关键 |大捆|避免桶装进口，启用R8 |
|高|重新渲染次数过多 | Zustand 选择器，React 编译器 |
|高|启动慢|禁用捆绑压缩、本机导航 |
|中 |动画滴|仅动画 `transform`/`opacity` |

## 新项目初始化

```bash
# 1. Create project
npx create-expo-app@latest my-app --template blank-typescript
cd my-app

# 2. Install Expo Router + core deps
npx expo install expo-router react-native-safe-area-context react-native-screens

# 3. (Optional) Common extras
npx expo install expo-image react-native-reanimated react-native-gesture-handler
```

然后配置：

1.在`package.json`中设置入口点：`"main": "expo-router/entry"`
2.在`app.json`中添加方案：`"scheme": "my-app"`
3.删除`App.tsx`和`index.ts`
4. 创建 `app/_layout.tsx` 作为根 Stack 布局
5.创建`app/(tabs)/_layout.tsx`用于选项卡导航
6.在`app/(tabs)/`中创建路线文件（参见[navigation.md](references/navigation.md)）

对于网络支持，还需安装：`npx expo install react-native-web react-dom @expo/metro-runtime`

## 核心原则

**写作前查阅参考资料**：在实现导航、列表、网络或项目设置时，请阅读上面匹配的参考文件以了解模式和陷阱。

**首先尝试 Expo Go** (`npx expo start`)。仅当使用本地 Expo 模块、Apple 目标或不在 Expo Go 中的第三方本机模块时才需要自定义构建 (`eas build`)。

**条件渲染**：使用 `{count > 0 && <Text />}` 而不是 `{count && <Text />}`（渲染“0”）。

**动画规则**：仅对 `transform` 和 `opacity` 进行动画处理 — GPU 合成，无布局抖动。

**导入**：始终直接从源导入，而不是桶文件 - 避免捆绑膨胀。

**列表和图像**：在使用 `FlatList` 或 RN `Image` 之前，请检查上面的组件首选项表 - `FlashList` 和 `expo-image` 几乎总是正确的选择。

**路由文件**：始终使用短横线大小写，切勿将组件/类型/实用程序放在 `app/` 中。

## 清单

### 新项目设置
- [ ] `tsconfig.json` 路径别名已配置
- [ ] `EXPO_PUBLIC_API_URL` 每个环境设置的环境变量
- [ ] 根布局有 `GestureHandlerRootView` （如果使用手势）
- [ ] `contentInsetAdjustmentBehavior="automatic"` 在所有滚动视图上
- [ ] `FlashList` 而不是 `FlatList` 用于列表 > 20 项

### 发货前
- [ ] `--profile` 模式下的配置文件，修复帧 > 16ms
- [ ] 捆绑包分析 (`source-map-explorer`)，无桶进口
- [ ] R8 支持 Android
- [ ] 关键路径的单元+组件测试
- [ ] E2E 登录、核心功能、结帐流程

---

Flutter开发→参见`flutter-dev`技巧。
iOS 原生（UIKit/SwiftUI）→参见 `ios-application-dev` 技巧。
Android 原生 (Kotlin/Compose) → 参见 `android-native-dev` 技巧。

*React Native 是 Meta Platforms, Inc. 的商标。Expo 是 650 Industries, Inc. 的商标。所有其他产品名称均为其各自所有者的商标。*
