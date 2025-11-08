import streamlit as st
import requests
import json
from typing import Dict

# Page config
st.set_page_config(
    page_title="Ticket Priority Classifier",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API endpoint
API_URL = "http://localhost:8000/classify-ticket"

# Custom CSS for better styling
st.markdown("""
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stAlert {
        margin-top: 1rem;
    }
    .priority-critical {
        background-color: #ff4444;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        font-weight: bold;
        font-size: 1.2rem;
        text-align: center;
    }
    .priority-high {
        background-color: #ff8800;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        font-weight: bold;
        font-size: 1.2rem;
        text-align: center;
    }
    .priority-medium {
        background-color: #ffbb00;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        font-weight: bold;
        font-size: 1.2rem;
        text-align: center;
    }
    .priority-low {
        background-color: #00cc44;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        font-weight: bold;
        font-size: 1.2rem;
        text-align: center;
    }
    .keyword-badge {
        display: inline-block;
        background-color: #e0e0e0;
        color: #333;
        padding: 0.2rem 0.5rem;
        border-radius: 0.3rem;
        margin: 0.2rem;
        font-size: 0.9rem;
    }
    .keyword-critical {
        background-color: #ffebee;
        color: #c62828;
        font-weight: bold;
    }
    .keyword-high {
        background-color: #fff3e0;
        color: #e65100;
    }
    .keyword-positive {
        background-color: #e8f5e9;
        color: #2e7d32;
    }
    </style>
""", unsafe_allow_html=True)

# Pre-loaded examples
EXAMPLES = {
    "🔴 Critical - Production Down": {
        "text": "URGENT! Production database is down and all customers are affected! We're losing revenue every minute!",
        "tier": "enterprise"
    },
    "🟠 High - Security Issue": {
        "text": "We have a security breach. Hackers may have compromised customer data. Need immediate help!",
        "tier": "premium"
    },
    "🟡 Medium - Login Problem": {
        "text": "I can't login to my account. This is frustrating and I need access soon.",
        "tier": "standard"
    },
    "🟢 Low - General Question": {
        "text": "Hello! I have a question about changing my profile picture. Thanks for your help!",
        "tier": "standard"
    },
    "🎯 Edge Case - Urgent but Positive": {
        "text": "I'm urgently excited about this new feature! Thanks so much for the amazing update!",
        "tier": "premium"
    }
}


def classify_ticket(text: str, customer_tier: str, ticket_id: str = None) -> Dict:
    """Call the API to classify a ticket."""
    try:
        payload = {
            "ticket_id": ticket_id,
            "text": text,
            "customer_tier": customer_tier
        }
        
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to API. Make sure the FastAPI server is running on http://localhost:8000")
        return None
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        return None


def display_priority(priority: str):
    """Display priority with color coding."""
    priority_classes = {
        "critical": "priority-critical",
        "high": "priority-high",
        "medium": "priority-medium",
        "low": "priority-low"
    }
    
    priority_icons = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🟢"
    }
    
    css_class = priority_classes.get(priority.lower(), "priority-low")
    icon = priority_icons.get(priority.lower(), "⚪")
    
    st.markdown(
        f'<div class="{css_class}">{icon} {priority.upper()}</div>',
        unsafe_allow_html=True
    )


def display_keywords(keywords_detected: Dict):
    """Display detected keywords with badges."""
    
    if keywords_detected.get("critical"):
        st.markdown("**🔴 Critical Keywords:**")
        keywords_html = ""
        for kw in keywords_detected["critical"]:
            keywords_html += f'<span class="keyword-badge keyword-critical">{kw}</span>'
        st.markdown(keywords_html, unsafe_allow_html=True)
    
    if keywords_detected.get("high"):
        st.markdown("**🟠 High Priority Keywords:**")
        keywords_html = ""
        for kw in keywords_detected["high"]:
            keywords_html += f'<span class="keyword-badge keyword-high">{kw}</span>'
        st.markdown(keywords_html, unsafe_allow_html=True)
    
    if keywords_detected.get("positive"):
        st.markdown("**🟢 Positive Keywords:**")
        keywords_html = ""
        for kw in keywords_detected["positive"]:
            keywords_html += f'<span class="keyword-badge keyword-positive">{kw}</span>'
        st.markdown(keywords_html, unsafe_allow_html=True)


def main():
    # Header
    st.title("🎫 Ticket Priority Classifier")
    st.markdown("**AI-powered support ticket prioritization using sentiment analysis and keyword detection**")
    st.divider()
    
    # Sidebar
    with st.sidebar:
        st.header("ℹ️ About")
        st.markdown("""
        This system uses:
        - **Sentiment Analysis** (35%)
        - **Keyword Detection** (45%)
        - **Customer Tier** (20%)
        
        To automatically classify support tickets into priority levels.
        """)
        
        st.divider()
        
        st.header("📊 Priority Levels")
        st.markdown("""
        - 🔴 **Critical** (>80%): Immediate action required
        - 🟠 **High** (60-80%): Urgent attention needed
        - 🟡 **Medium** (40-60%): Normal priority
        - 🟢 **Low** (<40%): Can be scheduled
        """)
        
        st.divider()
        
        # API Status
        st.header("🔌 API Status")
        try:
            health_response = requests.get("http://localhost:8000/health", timeout=2)
            if health_response.status_code == 200:
                st.success("✅ API Connected")
            else:
                st.error("❌ API Error")
        except:
            st.error("❌ API Offline")
            st.markdown("Start the API with: `python main.py`")
    
    # Main content
    tab1, tab2 = st.tabs(["🎯 Classify Ticket", "📋 Batch Classification"])
    
    with tab1:
        # Example selector
        st.subheader("Quick Examples")
        example_choice = st.selectbox(
            "Choose an example or write your own:",
            ["Custom"] + list(EXAMPLES.keys())
        )
        
        # Input fields
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if example_choice == "Custom":
                ticket_text = st.text_area(
                    "Ticket Text",
                    placeholder="Enter the support ticket text here...",
                    height=150
                )
            else:
                ticket_text = st.text_area(
                    "Ticket Text",
                    value=EXAMPLES[example_choice]["text"],
                    height=150
                )
        
        with col2:
            if example_choice == "Custom":
                default_tier = "standard"
            else:
                default_tier = EXAMPLES[example_choice]["tier"]
            
            customer_tier = st.selectbox(
                "Customer Tier",
                ["standard", "premium", "enterprise", "free"],
                index=["standard", "premium", "enterprise", "free"].index(default_tier)
            )
            
            ticket_id = st.text_input(
                "Ticket ID (optional)",
                placeholder="TKT-001"
            )
        
        # Classify button
        if st.button("🚀 Classify Ticket", type="primary", use_container_width=True):
            if not ticket_text:
                st.warning("⚠️ Please enter ticket text")
            else:
                with st.spinner("Analyzing ticket..."):
                    result = classify_ticket(ticket_text, customer_tier, ticket_id)
                
                if result:
                    st.divider()
                    
                    # Results section
                    st.subheader("📊 Classification Results")
                    
                    # Priority display
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.markdown("**Priority Level:**")
                        display_priority(result["priority"])
                    
                    with col2:
                        st.metric(
                            "Final Score",
                            f"{result['final_score']*100:.1f}%"
                        )
                    
                    with col3:
                        st.metric(
                            "Sentiment",
                            result["sentiment"].title(),
                            f"{result['sentiment_score']*100:.1f}%"
                        )
                    
                    st.divider()
                    
                    # Breakdown section
                    st.subheader("🔍 Scoring Breakdown")
                    
                    breakdown = result["breakdown"]
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Score Components:**")
                        
                        # Sentiment score
                        st.markdown(f"**Sentiment Score:** {breakdown['sentiment_score']*100:.1f}%")
                        st.progress(breakdown['sentiment_score'])
                        
                        # Keyword score
                        st.markdown(f"**Keyword Score:** {breakdown['keyword_score']*100:.1f}%")
                        st.progress(breakdown['keyword_score'])
                        
                        # Tier multiplier
                        st.markdown(f"**Tier Multiplier:** {breakdown['tier_multiplier']}x")
                        st.progress(min(breakdown['tier_multiplier'] / 1.5, 1.0))
                    
                    with col2:
                        st.markdown("**Detected Keywords:**")
                        display_keywords(breakdown['keywords_detected'])
                    
                    # JSON output (collapsible)
                    with st.expander("📄 View Raw JSON Response"):
                        st.json(result)
    
    with tab2:
        st.subheader("📋 Batch Classification")
        st.info("Coming soon: Upload CSV with multiple tickets for batch processing")
        
        # Placeholder for batch functionality
        st.markdown("""
        **Future features:**
        - Upload CSV file with tickets
        - Process multiple tickets at once
        - Export results to CSV
        - Compare tickets side-by-side
        """)


if __name__ == "__main__":
    main()