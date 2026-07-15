"""
لوحة تحكم البوت - بدون pandas
"""
from flask import Flask, render_template_string, request, jsonify, send_file
from datetime import datetime, timedelta
import asyncio
import asyncpg
import os
from io import BytesIO
import csv

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/sniper_bot")

async def get_db():
    conn = await asyncpg.connect(DATABASE_URL)
    return conn

@app.route('/')
def index():
    html = """
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>لوحة تحكم البوت</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: #0f0f0f; color: #fff; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            h1 { color: #00ff00; margin-bottom: 20px; }
            .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
            .stat-box { background: #1a1a1a; padding: 15px; border-left: 4px solid #00ff00; }
            .stat-value { font-size: 24px; font-weight: bold; color: #00ff00; }
            .stat-label { color: #888; font-size: 12px; }
            .filters { background: #1a1a1a; padding: 15px; margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap; }
            input, select { background: #222; color: #fff; border: 1px solid #444; padding: 8px; }
            button { background: #00ff00; color: #000; border: none; padding: 8px 15px; cursor: pointer; }
            table { width: 100%; border-collapse: collapse; background: #1a1a1a; }
            th, td { padding: 10px; text-align: right; border-bottom: 1px solid #333; }
            th { background: #000; }
            tr:hover { background: #252525; }
            .profit { color: #00ff00; }
            .loss { color: #ff0000; }
            .download-btn { margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 لوحة تحكم البوت</h1>
            
            <div class="stats">
                <div class="stat-box">
                    <div class="stat-value" id="total-profit">-</div>
                    <div class="stat-label">الربح الإجمالي (هذا الشهر)</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value" id="total-trades">-</div>
                    <div class="stat-label">إجمالي الصفقات</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value" id="win-rate">-</div>
                    <div class="stat-label">نسبة الرابح</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value" id="avg-profit">-</div>
                    <div class="stat-label">متوسط الربح</div>
                </div>
            </div>

            <div class="download-btn">
                <button onclick="downloadCSV()">📥 تنزيل CSV</button>
            </div>

            <div class="filters">
                <input type="date" id="from-date" placeholder="من">
                <input type="date" id="to-date" placeholder="إلى">
                <select id="status-filter">
                    <option value="">الكل</option>
                    <option value="won">رابح</option>
                    <option value="loss">خاسر</option>
                </select>
                <button onclick="loadTrades()">🔍 بحث</button>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>الوقت</th>
                        <th>الرمز</th>
                        <th>مبلغ الدخول</th>
                        <th>سعر الدخول</th>
                        <th>سعر الخروج</th>
                        <th>الربح/الخسارة</th>
                        <th>النسبة</th>
                        <th>الحالة</th>
                    </tr>
                </thead>
                <tbody id="trades-table">
                    <tr><td colspan="8" style="text-align: center; color: #888;">جاري التحميل...</td></tr>
                </tbody>
            </table>
        </div>

        <script>
        async function loadTrades() {
            const fromDate = document.getElementById('from-date').value;
            const toDate = document.getElementById('to-date').value;
            const status = document.getElementById('status-filter').value;
            
            const response = await fetch(`/api/trades?from_date=${fromDate}&to_date=${toDate}&status=${status}`);
            const data = await response.json();
            
            const tbody = document.getElementById('trades-table');
            tbody.innerHTML = '';
            
            if (data.trades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #888;">لا توجد صفقات</td></tr>';
                return;
            }
            
            data.trades.forEach(trade => {
                const row = document.createElement('tr');
                const profitClass = (trade[6] || 0) >= 0 ? 'profit' : 'loss';
                row.innerHTML = `
                    <td>${new Date(trade[3]).toLocaleString('ar-SA')}</td>
                    <td>${trade[2]}</td>
                    <td>${parseFloat(trade[4]).toFixed(4)} SOL</td>
                    <td>${parseFloat(trade[5]).toFixed(6)}</td>
                    <td>${trade[6] ? parseFloat(trade[6]).toFixed(6) : '-'}</td>
                    <td class="${profitClass}">${trade[7] ? parseFloat(trade[7]).toFixed(6) : '-'}</td>
                    <td class="${profitClass}">${trade[8] ? parseFloat(trade[8]).toFixed(2) : '-'}%</td>
                    <td>${trade[9]}</td>
                `;
                tbody.appendChild(row);
            });
            
            document.getElementById('total-profit').textContent = `${data.stats.total_profit.toFixed(4)} SOL`;
            document.getElementById('total-trades').textContent = data.stats.total_trades;
            document.getElementById('win-rate').textContent = `${data.stats.win_rate.toFixed(1)}%`;
            document.getElementById('avg-profit').textContent = `${data.stats.avg_profit.toFixed(4)} SOL`;
        }

        async function downloadCSV() {
            const response = await fetch('/api/export-csv');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `trades_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
        }

        window.onload = loadTrades;
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/api/trades')
async def get_trades():
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    status = request.args.get('status', '')
    
    conn = await get_db()
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    
    if from_date:
        query += " AND entry_time >= $" + str(len(params) + 1)
        params.append(datetime.fromisoformat(from_date))
    
    if to_date:
        query += " AND entry_time <= $" + str(len(params) + 1)
        params.append(datetime.fromisoformat(to_date) + timedelta(days=1))
    
    if status == 'won':
        query += " AND profit_pct > 0"
    elif status == 'loss':
        query += " AND profit_pct < 0"
    
    query += " ORDER BY entry_time DESC LIMIT 1000"
    
    trades = await conn.fetch(query, *params)
    
    total_profit = sum(float(t['profit_loss'] or 0) for t in trades)
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if (float(t['profit_pct'] or 0)) > 0)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    avg_profit = total_profit / total_trades if total_trades > 0 else 0
    
    await conn.close()
    
    return jsonify({
        'trades': trades,
        'stats': {
            'total_profit': total_profit,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
        }
    })

@app.route('/api/export-csv')
async def export_csv():
    conn = await get_db()
    trades = await conn.fetch("SELECT * FROM trades ORDER BY entry_time DESC")
    await conn.close()
    
    output = BytesIO()
    if trades:
        headers = trades[0].keys()
        output.write(','.join(str(h) for h in headers).encode('utf-8-sig'))
        output.write(b'\n')
        
        for trade in trades:
            values = [str(trade[h]) for h in headers]
            output.write(','.join(values).encode('utf-8-sig'))
            output.write(b'\n')
    
    output.seek(0)
    return send_file(output, mimetype='text/csv',
                     as_attachment=True, download_name=f'trades_{datetime.now().date()}.csv')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
