import os
import re
import logging
import discord
from discord import app_commands
from dotenv import load_dotenv
from urllib.parse import urlparse

from database import init_db, add_watched_site, remove_watched_site, get_watched_sites
from archive_service import ArchiveService
from renderer import ArchiveRenderer

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# URL regex pattern
URL_PATTERN = re.compile(
    r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*',
    re.IGNORECASE
)


class ArchiveBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        
        self.tree = app_commands.CommandTree(self)
        self.archive_service = ArchiveService()
        self.archive_renderer = ArchiveRenderer()
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        await init_db()
        self._register_commands()
        await self.tree.sync()
    
    def _register_commands(self):
        """Register all slash commands."""
        
        @self.tree.command(name="addsite", description="Add a domain to the watched sites list")
        @app_commands.describe(domain="The domain to add (e.g., nytimes.com)")
        @app_commands.checks.has_permissions(manage_messages=True)
        async def add_site(interaction: discord.Interaction, domain: str):
            if not interaction.guild:
                await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
                return
            
            # Clean up the domain
            domain = domain.lower().strip()
            if domain.startswith("http"):
                parsed = urlparse(domain)
                domain = parsed.netloc
            
            if domain.startswith("www."):
                domain = domain[4:]
            
            if not domain:
                await interaction.response.send_message("Please provide a valid domain.", ephemeral=True)
                return
            
            added = await add_watched_site(str(interaction.guild.id), domain, str(interaction.user))
            if added:
                await interaction.response.send_message(f"Added `{domain}` to the watched sites list.")
            else:
                await interaction.response.send_message(f"`{domain}` is already in the watched sites list.")
        
        @self.tree.command(name="removesite", description="Remove a domain from the watched sites list")
        @app_commands.describe(domain="The domain to remove")
        @app_commands.checks.has_permissions(manage_messages=True)
        async def remove_site(interaction: discord.Interaction, domain: str):
            if not interaction.guild:
                await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
                return
            
            domain = domain.lower().strip()
            if domain.startswith("www."):
                domain = domain[4:]
            
            removed = await remove_watched_site(str(interaction.guild.id), domain)
            if removed:
                await interaction.response.send_message(f"Removed `{domain}` from the watched sites list.")
            else:
                await interaction.response.send_message(f"`{domain}` was not in the watched sites list.")
        
        @self.tree.command(name="listsites", description="List all sites being monitored for archiving")
        async def list_sites(interaction: discord.Interaction):
            if not interaction.guild:
                await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
                return
            
            sites = await get_watched_sites(str(interaction.guild.id))
            
            if not sites:
                await interaction.response.send_message("No sites are currently being monitored.")
                return
            
            site_list = "\n".join(f"• `{site}`" for site in sites)
            
            embed = discord.Embed(
                title="Monitored Sites",
                description=site_list,
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Total: {len(sites)} sites")
            
            await interaction.response.send_message(embed=embed)
        
        @self.tree.command(name="archive", description="Get archive.today links for a URL")
        @app_commands.describe(url="The URL to get archive links for")
        async def archive(interaction: discord.Interaction, url: str):
            if not url.startswith("http"):
                url = "https://" + url
            
            links = self.archive_service.get_links(url)
            
            embed = discord.Embed(
                title="Archive Links",
                description="Use these links to find or create an archived version.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Search Existing Archives", value=links.search_url, inline=False)
            embed.add_field(name="Create New Archive", value=links.save_url, inline=False)
            
            await interaction.response.send_message(embed=embed)
        
        @self.tree.command(name="render", description="Create an archived version of a URL")
        @app_commands.describe(url="The URL to archive")
        async def render(interaction: discord.Interaction, url: str):
            logger.info(f"/render command received for URL: {url}")
            
            if not url.startswith("http"):
                url = "https://" + url
            
            await interaction.response.defer()
            
            embed = discord.Embed(
                title="Archiving Page",
                description="Creating an archived version of this page. This may take a few minutes...",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed)
            
            logger.info("Starting archive_renderer.render_archive...")
            result = await self.archive_renderer.render_archive(url)
            logger.info(f"render_archive completed. Success: {result.success}, Error: {result.error}")
            
            if result.success and result.archive_url:
                embed = discord.Embed(
                    title="Archive Created",
                    description="Successfully created an archived version.",
                    color=discord.Color.green()
                )
                embed.add_field(name="Archive URL", value=result.archive_url, inline=False)
            elif not result.success and "Timeout" in str(result.error):
                links = self.archive_service.get_links(url)
                embed = discord.Embed(
                    title="Archive Render Timeout",
                    description="Timed out waiting for archive to render",
                    color=discord.Color.orange()
                )
                embed.add_field(
                    name="Check Archive Progress",
                    value=f"[Check archive progress manually]({links.save_url})",
                    inline=False
                )
            else:
                links = self.archive_service.get_links(url)
                embed = discord.Embed(
                    title="Archive Failed",
                    description="Could not automatically archive this page.",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="Archive Manually",
                    value=f"[Search existing archives]({links.search_url}) or [create new archive]({links.save_url})",
                    inline=False
                )
            
            # Edit the original message
            message = await interaction.original_response()
            await message.edit(embed=embed)
    
    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
    
    async def on_message(self, message: discord.Message):
        """Listen for messages containing URLs from watched sites."""
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        # Find all URLs in the message
        urls = URL_PATTERN.findall(message.content)
        
        if not urls:
            return
        
        watched_sites = await get_watched_sites(str(message.guild.id))
        if not watched_sites:
            return
        
        for url in urls:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                
                # Remove www. prefix for matching
                if domain.startswith("www."):
                    domain = domain[4:]
                
                # Check if this domain matches any watched site
                is_watched = any(
                    watched_domain in domain or domain in watched_domain
                    for watched_domain in watched_sites
                )
                
                if is_watched:
                    await self._handle_watched_url(message, url)
                    
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}")
    
    async def _handle_watched_url(self, message: discord.Message, url: str):
        """Handle a URL from a watched site by rendering an archive."""
        # Send initial status message
        embed = discord.Embed(
            title="Archiving Page",
            description="Creating an archived version of this page. This may take a few minutes...",
            color=discord.Color.orange()
        )
        status_msg = await message.reply(embed=embed, mention_author=False)
        
        # Render the archive
        result = await self.archive_renderer.render_archive(url)
        
        if result.success and result.archive_url:
            embed = discord.Embed(
                title="Archived Version",
                description="Successfully created an archived version.",
                color=discord.Color.green()
            )
            embed.add_field(name="Archive URL", value=result.archive_url, inline=False)
        else:
            # Provide manual links on failure
            links = self.archive_service.get_links(url)
            embed = discord.Embed(
                title="Archive Failed",
                description="Could not automatically archive this page.",
                color=discord.Color.red()
            )
            embed.add_field(
                name="Archive Manually",
                value=f"[Search existing archives]({links.search_url}) or [create new archive]({links.save_url})",
                inline=False
            )
        
        await status_msg.edit(embed=embed)
    
    async def close(self):
        """Cleanup when bot shuts down."""
        await self.archive_service.close()
        await self.archive_renderer.close()
        await super().close()


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN environment variable not set.")
        return
    
    bot = ArchiveBot()
    bot.run(token)


if __name__ == "__main__":
    main()
