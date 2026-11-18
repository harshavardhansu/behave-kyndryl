// The Command Centre's two charts, in their own chunk: the chart library (~350 kB) loads after the page's
// text and numbers, which matters on phones. Overview keeps the chart areas sized, so nothing shifts.
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export function TrendChart({ data }: { data: object[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} barSize={27} margin={{ top: 12, right: 12, left: -28, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 4" vertical={false} stroke="#ECEDEF" />
        <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: '#707378', fontSize: 11 }} dy={8} />
        <YAxis axisLine={false} tickLine={false} tick={{ fill: '#707378', fontSize: 11 }} allowDecimals={false} />
        <Tooltip cursor={{ fill: '#F5F5F5' }} contentStyle={{ borderRadius: 6, border: '1px solid #E5E5E5', fontSize: 12 }} />
        <Bar isAnimationActive={false} dataKey="other" name="Medium & low" stackId="incidents" fill="#E5E5E5" />
        <Bar isAnimationActive={false} dataKey="high" name="High" stackId="incidents" fill="#8D9095" />
        <Bar isAnimationActive={false} dataKey="critical" name="Critical" stackId="incidents" fill="#F5362A" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function HealthDonut({ health }: { health: { name: string; value: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie isAnimationActive={false} data={health} dataKey="value" innerRadius={49} outerRadius={64} startAngle={90} endAngle={-270} paddingAngle={4} stroke="none">
          {health.map((item, index) => (
            <Cell key={item.name} fill={['#45494E', '#D6D7D9', '#F5362A'][index]} />
          ))}
        </Pie>
      </PieChart>
    </ResponsiveContainer>
  )
}
