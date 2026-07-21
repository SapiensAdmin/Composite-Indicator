import './globals.css';

export const metadata = {
  title: 'AMFI Liquidity-Stress Composite',
  description:
    'A custom, registry-weighted composite of AMFI mid-cap & small-cap stress-test / liquidity disclosures. Monthly regime gauge.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
