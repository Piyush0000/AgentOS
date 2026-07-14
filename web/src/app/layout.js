import './globals.css';

export const metadata = {
  title: 'AgentOS Observability Dashboard',
  description: 'Enterprise Observability and Security Control Plane for AI Agents',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  );
}
