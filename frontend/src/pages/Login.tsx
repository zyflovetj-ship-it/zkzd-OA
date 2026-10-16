import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, Form, Input, Typography, message } from "antd";
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from "@ant-design/icons";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";

const FEATURES = [
  "流程审批 · 电子签单 · 审批委托",
  "考勤打卡 · 请假加班 · 外勤工单",
  "费用报销 · 预算管控 · 批量打款",
  "公文流转 · 文档版本 · 传阅回执",
  "建模引擎 · 报表中心 · 审计日志",
];

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const onFinish = async (v: { username: string; password: string }) => {
    setLoading(true);
    try {
      await login(v.username, v.password);
      navigate("/");
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "登录失败";
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="zk-login">
      {/* 左侧品牌区：品牌渐变 + 白色标识 */}
      <aside className="zk-login__brand">
        <div className="zk-login__brand-inner">
          <img className="zk-login__logo" src="/brand/logo-lockup-white.png" alt="中科智电" />
          <h1 className="zk-login__slogan">协同办公平台</h1>
          <p className="zk-login__desc">
            面向电力工程业务的统一协同底座，把审批、考勤、报销、公文与数据建模收敛到一个工作台。
          </p>
          <ul className="zk-login__features">
            {FEATURES.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      </aside>

      {/* 右侧登录表单 */}
      <main className="zk-login__panel">
        <Card className="zk-login__card" variant="borderless">
          <div className="zk-login__head">
            <SafetyCertificateOutlined className="zk-login__head-icon" />
            <div>
              <Typography.Title level={4} style={{ margin: 0 }}>
                欢迎登录
              </Typography.Title>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                请使用企业账号登录协同办公平台
              </Typography.Text>
            </div>
          </div>

          <Form
            layout="vertical"
            size="large"
            onFinish={onFinish}
            initialValues={{ username: "admin", password: "admin123" }}
            style={{ marginTop: 24 }}
          >
            <Form.Item
              name="username"
              label="账号"
              rules={[{ required: true, message: "请输入用户名" }]}
            >
              <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 8 }}>
              <Button type="primary" htmlType="submit" block loading={loading}>
                登录
              </Button>
            </Form.Item>
          </Form>

          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            演示账号 admin / admin123，正式环境请及时修改默认密码。
          </Typography.Text>
        </Card>
        <div className="zk-login__foot">© 中科智电 · 协同办公平台</div>
      </main>
    </div>
  );
}
