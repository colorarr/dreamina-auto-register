const { SocksProxyAgent } = require('socks-proxy-agent');
const axios = require('axios');

async function test() {
    const proxyUrl = process.env.TEST_PROXY_URL || "socks5://PROXY_USER:PROXY_PASSWORD@127.0.0.1:1080";
    console.log("Testing configured proxy");
    const agent = new SocksProxyAgent(proxyUrl);
    try {
        const res = await axios.get("http://ip-api.com/json/", {
            httpAgent: agent,
            httpsAgent: agent,
            proxy: false,
            timeout: 10000
        });
        console.log("Success:", res.data);
    } catch (err) {
        console.error("Error:", err.message);
    }
}
test();
