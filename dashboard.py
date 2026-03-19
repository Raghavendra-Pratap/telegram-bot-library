"""
Web Dashboard for Bot Monitoring
Provides a web interface to monitor and control bots
"""
from flask import Flask, jsonify, render_template_string
from datetime import datetime
import json

from port_utils import find_available_port

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Telegram Bot Launcher - Dashboard</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            padding: 20px;
            min-height: 100vh;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            text-align: center;
        }
        .header h1 {
            color: #667eea;
            margin-bottom: 10px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .stat-card h3 {
            color: #667eea;
            margin-bottom: 10px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #333;
        }
        .bots-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
        }
        .bot-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .bot-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.15);
        }
        .bot-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .bot-name {
            font-size: 18px;
            font-weight: bold;
            color: #333;
        }
        .status-badge {
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }
        .status-running {
            background: #10b981;
            color: white;
        }
        .status-stopped {
            background: #ef4444;
            color: white;
        }
        .bot-info {
            margin-bottom: 10px;
        }
        .bot-info-item {
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            border-bottom: 1px solid #eee;
            font-size: 14px;
        }
        .bot-info-label {
            color: #666;
        }
        .bot-info-value {
            font-weight: 500;
            color: #333;
        }
        .bot-actions {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
            flex: 1;
        }
        .btn-start {
            background: #10b981;
            color: white;
        }
        .btn-start:hover {
            background: #059669;
        }
        .btn-stop {
            background: #ef4444;
            color: white;
        }
        .btn-stop:hover {
            background: #dc2626;
        }
        .btn-restart {
            background: #f59e0b;
            color: white;
        }
        .btn-restart:hover {
            background: #d97706;
        }
        .uptime {
            color: #10b981;
            font-weight: 600;
        }
        .refresh-info {
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 14px;
        }
        .error-message {
            background: #fee2e2;
            color: #991b1b;
            padding: 10px;
            border-radius: 5px;
            margin-top: 10px;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Telegram Bot Launcher Dashboard</h1>
            <p>Monitor and control your Telegram bots</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Bots</h3>
                <div class="stat-value" id="total-bots">0</div>
            </div>
            <div class="stat-card">
                <h3>Running</h3>
                <div class="stat-value" id="running-bots" style="color: #10b981;">0</div>
            </div>
            <div class="stat-card">
                <h3>Stopped</h3>
                <div class="stat-value" id="stopped-bots" style="color: #ef4444;">0</div>
            </div>
            <div class="stat-card">
                <h3>Total Uptime</h3>
                <div class="stat-value" id="total-uptime" style="font-size: 24px;">0h</div>
            </div>
        </div>
        
        <div class="bots-grid" id="bots-grid">
            <!-- Bots will be loaded here -->
        </div>
        
        <div class="refresh-info">
            Auto-refreshing every 3 seconds
        </div>
    </div>
    
    <script>
        function formatUptime(seconds) {
            if (!seconds) return '0s';
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = Math.floor(seconds % 60);
            
            if (hours > 0) {
                return `${hours}h ${minutes}m`;
            } else if (minutes > 0) {
                return `${minutes}m ${secs}s`;
            } else {
                return `${secs}s`;
            }
        }
        
        function formatTime(dateString) {
            if (!dateString) return 'N/A';
            const date = new Date(dateString);
            return date.toLocaleString();
        }
        
        async function loadBots() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                // Update stats
                document.getElementById('total-bots').textContent = data.total_bots;
                document.getElementById('running-bots').textContent = data.running_count;
                document.getElementById('stopped-bots').textContent = data.stopped_count;
                
                const totalUptime = data.bots.reduce((sum, bot) => sum + (bot.uptime_seconds || 0), 0);
                const hours = Math.floor(totalUptime / 3600);
                document.getElementById('total-uptime').textContent = `${hours}h`;
                
                // Render bots
                const botsGrid = document.getElementById('bots-grid');
                botsGrid.innerHTML = data.bots.map(bot => `
                    <div class="bot-card">
                        <div class="bot-header">
                            <div class="bot-name">${bot.name}</div>
                            <span class="status-badge ${bot.status === 'running' ? 'status-running' : 'status-stopped'}">
                                ${bot.status}
                            </span>
                        </div>
                        <div class="bot-info">
                            <div class="bot-info-item">
                                <span class="bot-info-label">Description:</span>
                                <span class="bot-info-value">${bot.description || 'N/A'}</span>
                            </div>
                            ${bot.status === 'running' ? `
                                <div class="bot-info-item">
                                    <span class="bot-info-label">PID:</span>
                                    <span class="bot-info-value">${bot.pid || 'N/A'}</span>
                                </div>
                                <div class="bot-info-item">
                                    <span class="bot-info-label">Uptime:</span>
                                    <span class="bot-info-value uptime">${formatUptime(bot.uptime_seconds)}</span>
                                </div>
                                ${bot.port ? `
                                <div class="bot-info-item">
                                    <span class="bot-info-label">Port:</span>
                                    <span class="bot-info-value">${bot.port}</span>
                                </div>
                                ` : ''}
                                <div class="bot-info-item">
                                    <span class="bot-info-label">Started:</span>
                                    <span class="bot-info-value">${formatTime(bot.start_time)}</span>
                                </div>
                            ` : ''}
                        </div>
                        ${bot.last_error ? `
                            <div class="error-message">
                                <strong>Last Error:</strong> ${bot.last_error.substring(0, 100)}...
                            </div>
                        ` : ''}
                        <div class="bot-actions">
                            ${bot.status === 'running' ? `
                                <button class="btn btn-stop" onclick="stopBot('${bot.id}')">Stop</button>
                                <button class="btn btn-restart" onclick="restartBot('${bot.id}')">Restart</button>
                            ` : `
                                <button class="btn btn-start" onclick="startBot('${bot.id}')">Start</button>
                            `}
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                console.error('Error loading bots:', error);
            }
        }
        
        async function startBot(botId) {
            try {
                const response = await fetch(`/api/start/${botId}`, { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    setTimeout(loadBots, 1000);
                } else {
                    alert('Error: ' + (data.error || 'Failed to start bot'));
                }
            } catch (error) {
                alert('Error starting bot: ' + error.message);
            }
        }
        
        async function stopBot(botId) {
            if (!confirm('Are you sure you want to stop this bot?')) return;
            try {
                const response = await fetch(`/api/stop/${botId}`, { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    setTimeout(loadBots, 1000);
                } else {
                    alert('Error: ' + (data.error || 'Failed to stop bot'));
                }
            } catch (error) {
                alert('Error stopping bot: ' + error.message);
            }
        }
        
        async function restartBot(botId) {
            if (!confirm('Are you sure you want to restart this bot?')) return;
            try {
                const response = await fetch(`/api/restart/${botId}`, { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    setTimeout(loadBots, 2000);
                } else {
                    alert('Error: ' + (data.error || 'Failed to restart bot'));
                }
            } catch (error) {
                alert('Error restarting bot: ' + error.message);
            }
        }
        
        // Load bots on page load
        loadBots();
        
        // Auto-refresh every 3 seconds
        setInterval(loadBots, 3000);
    </script>
</body>
</html>
"""

def start_dashboard(launcher, host='0.0.0.0', port=5000, port_holder=None):
    """Start the Flask dashboard server. If port is in use, tries the next ports until one is free.
    port_holder: optional list; when provided, port_holder[0] is set to the actual port used (so the launcher can print the URL).
    """
    preferred = port
    port = find_available_port(port)
    if port != preferred:
        import sys
        print(f"   Port {preferred} in use → using port {port}", file=sys.stderr)
    if port_holder is not None:
        port_holder[0] = port
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        return render_template_string(DASHBOARD_HTML)
    
    @app.route('/api/status')
    def api_status():
        """Get status of all bots"""
        available_bots = launcher.get_available_bots()
        running_bots = launcher.running_bots
        
        bots_data = []
        for bot in available_bots:
            bot_id = bot['id']
            bot_process = running_bots.get(bot_id)
            
            if bot_process and bot_process.process.poll() is None:
                # Bot is running
                uptime = (datetime.now() - bot_process.start_time).total_seconds()
                bots_data.append({
                    'id': bot_id,
                    'name': bot['name'],
                    'description': bot.get('description', ''),
                    'status': 'running',
                    'pid': bot_process.pid,
                    'port': bot_process.port,
                    'uptime_seconds': uptime,
                    'start_time': bot_process.start_time.isoformat(),
                    'last_error': bot_process.last_error
                })
            else:
                # Bot is stopped
                bots_data.append({
                    'id': bot_id,
                    'name': bot['name'],
                    'description': bot.get('description', ''),
                    'status': 'stopped',
                    'pid': None,
                    'port': bot.get('port'),
                    'uptime_seconds': 0,
                    'start_time': None,
                    'last_error': None
                })
        
        return jsonify({
            'total_bots': len(available_bots),
            'running_count': len([b for b in bots_data if b['status'] == 'running']),
            'stopped_count': len([b for b in bots_data if b['status'] == 'stopped']),
            'bots': bots_data
        })
    
    @app.route('/api/start/<bot_id>', methods=['POST'])
    def api_start(bot_id):
        """Start a bot"""
        try:
            bot_config = next((b for b in launcher.config['bots'] if b['id'] == bot_id), None)
            if not bot_config:
                return jsonify({'success': False, 'error': 'Bot not found'}), 404
            
            bot_process = launcher.start_bot(bot_config)
            if bot_process:
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': 'Failed to start bot'}), 500
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/stop/<bot_id>', methods=['POST'])
    def api_stop(bot_id):
        """Stop a bot"""
        try:
            success = launcher.stop_bot(bot_id)
            return jsonify({'success': success})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/restart/<bot_id>', methods=['POST'])
    def api_restart(bot_id):
        """Restart a bot"""
        try:
            success = launcher.restart_bot(bot_id)
            return jsonify({'success': success})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/stats')
    def api_stats():
        """Get statistics"""
        stats_data = {}
        for bot_id, stats in launcher.stats.items():
            bot_config = next((b for b in launcher.config['bots'] if b['id'] == bot_id), None)
            bot_name = bot_config['name'] if bot_config else bot_id
            
            stats_data[bot_id] = {
                'name': bot_name,
                'start_count': stats['start_count'],
                'stop_count': stats['stop_count'],
                'restart_count': stats['restart_count'],
                'total_uptime_hours': stats['total_uptime'] / 3600,
                'error_count': len(stats['errors'])
            }
        
        return jsonify(stats_data)
    
    # Run the Flask app (port was already chosen as available)
    app.run(host=host, port=port, debug=False, threaded=True)
