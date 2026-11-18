from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_aimodel_last_tested_at_aimodel_test_latency_ms"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContentReviewRule",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("forbidden_text", models.TextField()),
                ("replacement_text", models.TextField(blank=True, default="")),
                ("enabled", models.BooleanField(db_index=True, default=True)),
            ],
            options={"db_table": "content_review_rule", "ordering": ["id"]},
        ),
    ]
